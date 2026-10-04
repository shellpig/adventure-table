"""M07-C C2: atomic Tactical monster load from a battle map's saved placements.

Runs entirely inside the ``combat.started`` event transaction (one
Connection): map row lock, saved placements read, custom template rows locked
in id order, latest template resolution, full-batch validation against the
frozen board geometry, then Monster Instance / Combat entry creation. Any
failure rolls the whole start back: no half Combat, no stray Instances, no
early notifier.
"""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any
from uuid import UUID, uuid4

from sqlalchemy import select
from sqlalchemy.engine import Connection

from app.content.identity import parse_stable_key
from app.content.localization import ContentLocalizationCatalog
from app.content.p4a_combat_templates import monster_to_reusable_rules
from app.content.p4a_monsters import MonsterData
from app.content.registry import ContentRegistry, ContentValidationError
from app.domain.battle_maps.placements import (
    PLACEMENT_PROBLEM_INVALID_SIZE,
    PlacementProblem,
    PlacementValidationEntry,
    resolve_placement_size,
    validate_monster_placements,
)
from app.domain.battle_maps.schemas import (
    BattleMapArchivedError,
    BattleMapNotFoundError,
    MapMonsterPlacementInvalidError,
    MonsterPlacementProblem,
    MonsterPlacementReferenceNotFoundError,
    MonsterPlacementSourceError,
)
from app.domain.combat.monster_instances import initial_monster_resources
from app.domain.spatial.primitives import (
    BarrierSegment,
    GridCell,
    footprint_for_size,
)
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.battle_maps.tables import battle_maps
from app.persistence.combat.lifecycle import NewCombatEntry
from app.persistence.combat.repository import MonsterRepository, StoredMonsterInstance
from app.persistence.combat.tables import monster_templates

if TYPE_CHECKING:
    from app.domain.combat.resolution import SizeCategory
    from app.persistence.combat_boards.repository import StoredCombatBoard


@dataclass(frozen=True)
class MonsterLoadPlacement:
    """Board position spec for one loaded monster (aligned with entries)."""

    anchor_x: int
    anchor_y: int
    footprint_width: int
    footprint_height: int


@dataclass(frozen=True)
class MonsterLoadOutcome:
    """Result of the in-transaction monster load."""

    entries: tuple[NewCombatEntry, ...]
    placements: tuple[MonsterLoadPlacement, ...]


@dataclass(frozen=True)
class _ResolvedLoadSource:
    placement_id: UUID
    template_key: str | None
    custom_template_id: UUID | None
    anchor_x: int
    anchor_y: int
    visibility: str
    size: SizeCategory | None
    instance_name: str
    names: dict[str, str]
    name_is_custom: bool
    rules: dict[str, Any]
    template_revision: int | None


def _builtin_names(
    entry: MonsterData, content_localization: ContentLocalizationCatalog | None
) -> dict[str, str]:
    names: dict[str, str] = {"en": entry.name}
    if content_localization is not None:
        try:
            field = content_localization.resolve_field(entry.key, "name", "zh-TW")
        except ContentValidationError:
            # Best-effort overlay: a missing/invalid name overlay falls back
            # to the canonical English name instead of failing the load.
            return names
        if field.source == "overlay" and isinstance(field.value, str) and field.value.strip():
            names["zh-TW"] = field.value.strip()
    return names


def _frozen_barriers_and_blocked(
    baseline: dict[str, Any],
) -> tuple[tuple[BarrierSegment, ...], frozenset[GridCell]]:
    """Barriers / blocked cells from the frozen board baseline.

    Same semantics as the C1 editor validator and ``CombatBoardService._barriers``:
    every wall blocks, and any door whose frozen state is not ``open`` blocks.
    """
    barriers = [
        BarrierSegment(x1=wall["x1"], y1=wall["y1"], x2=wall["x2"], y2=wall["y2"])
        for wall in baseline.get("walls", [])
    ]
    barriers.extend(
        BarrierSegment(x1=door["x1"], y1=door["y1"], x2=door["x2"], y2=door["y2"])
        for door in baseline.get("doors", [])
        if door.get("state") != "open"
    )
    blocked = frozenset(
        GridCell(x=cell["x"], y=cell["y"])
        for cell in baseline.get("terrain", [])
        if cell.get("terrain_kind") == "blocked"
    )
    return tuple(barriers), blocked


def load_map_monsters(
    connection: Connection,
    *,
    room_id: UUID,
    campaign_id: UUID,
    battle_map_id: UUID,
    battle_map_repository: BattleMapRepository,
    monster_repository: MonsterRepository,
    content_registry: ContentRegistry,
    content_localization: ContentLocalizationCatalog | None,
    board: StoredCombatBoard,
    now: datetime,
) -> MonsterLoadOutcome:
    """Resolve, validate, and create one Monster Instance per saved placement.

    Must be called inside the ``combat.started`` event transaction. Lock order:
    battle_maps row (FOR UPDATE), then custom monster_templates rows in id
    order. Archived custom templates are loadable here: the map's saved
    configuration is the authority, and C1 already gated new archived
    references at edit time. Missing / cross-Room templates are 404; any
    placement problem fails the whole batch with 409
    ``map_monster_placement_invalid`` (problems are DM-only upstream).
    """
    map_row = connection.execute(
        select(battle_maps.c.id, battle_maps.c.archived_at)
        .where(battle_maps.c.id == battle_map_id, battle_maps.c.room_id == room_id)
        .with_for_update()
    ).mappings().one_or_none()
    if map_row is None:
        raise BattleMapNotFoundError(f"Battle map {battle_map_id} not found")
    if map_row["archived_at"] is not None:
        raise BattleMapArchivedError(f"Battle map {battle_map_id} is archived")

    placements = battle_map_repository.get_placements(battle_map_id, connection=connection)
    if not placements:
        return MonsterLoadOutcome(entries=(), placements=())

    custom_ids = sorted(
        {placement.custom_template_id for placement in placements if placement.custom_template_id is not None}
    )
    template_rows: dict[UUID, dict[str, Any]] = {}
    if custom_ids:
        rows = connection.execute(
            select(
                monster_templates.c.id,
                monster_templates.c.room_id,
                monster_templates.c.name,
                monster_templates.c.rules,
                monster_templates.c.revision,
                monster_templates.c.presentation_json,
                monster_templates.c.archived_at,
            )
            .where(monster_templates.c.id.in_(custom_ids))
            .order_by(monster_templates.c.id)
            .with_for_update()
        ).mappings().all()
        template_rows = {row["id"]: dict(row) for row in rows}

    resolved: list[_ResolvedLoadSource] = []
    problems: list[PlacementProblem] = []
    for placement in placements:
        if placement.template_key is not None:
            entry = content_registry.get_optional(placement.template_key)
            if entry is None:
                raise MonsterPlacementReferenceNotFoundError(
                    f"monster template '{placement.template_key}' not found"
                )
            if parse_stable_key(entry.key).kind != "monster":
                raise MonsterPlacementSourceError(
                    f"content entry '{placement.template_key}' is not a monster"
                )
            data = entry.data if isinstance(entry.data, dict) else {}
            size = resolve_placement_size(data.get("size"))
            rules = monster_to_reusable_rules(MonsterData.model_validate(entry.data))
            names = _builtin_names(entry, content_localization)
            resolved.append(
                _ResolvedLoadSource(
                    placement_id=placement.id,
                    template_key=placement.template_key,
                    custom_template_id=None,
                    anchor_x=placement.anchor_x,
                    anchor_y=placement.anchor_y,
                    visibility=placement.visibility,
                    size=size,
                    instance_name=entry.name,
                    names=names,
                    name_is_custom=False,
                    rules=rules,
                    template_revision=None,
                )
            )
        else:
            template_id = placement.custom_template_id
            assert template_id is not None
            row = template_rows.get(template_id)
            if row is None or row["room_id"] != room_id:
                raise MonsterPlacementReferenceNotFoundError(
                    f"monster template '{template_id}' not found in this room"
                )
            rules = row["rules"] if isinstance(row["rules"], dict) else {}
            size = resolve_placement_size(rules.get("size"))
            presentation = row["presentation_json"] if isinstance(row["presentation_json"], dict) else {}
            names = dict(presentation.get("names") or {"en": str(row["name"])})
            name_is_custom = bool(presentation.get("name_is_custom", True))
            resolved.append(
                _ResolvedLoadSource(
                    placement_id=placement.id,
                    template_key=None,
                    custom_template_id=template_id,
                    anchor_x=placement.anchor_x,
                    anchor_y=placement.anchor_y,
                    visibility=placement.visibility,
                    size=size,
                    instance_name=str(row["name"]),
                    names=names,
                    name_is_custom=name_is_custom,
                    rules=rules,
                    template_revision=int(row["revision"]),
                )
            )
        if resolved[-1].size is None:
            problems.append(
                PlacementProblem(
                    placement_id=placement.id, code=PLACEMENT_PROBLEM_INVALID_SIZE
                )
            )

    validation_entries = [
        PlacementValidationEntry(
            placement_id=item.placement_id,
            size=item.size,
            anchor_x=item.anchor_x,
            anchor_y=item.anchor_y,
        )
        for item in resolved
        if item.size is not None
    ]
    barriers, blocked = _frozen_barriers_and_blocked(dict(board.baseline))
    problems.extend(
        validate_monster_placements(
            validation_entries,
            width_cells=board.width_cells,
            height_cells=board.height_cells,
            barriers=barriers,
            blocked_cells=blocked,
        )
    )
    if problems:
        raise MapMonsterPlacementInvalidError(
            [
                MonsterPlacementProblem(placement_id=problem.placement_id, code=problem.code)
                for problem in problems
            ]
        )

    entries: list[NewCombatEntry] = []
    load_placements: list[MonsterLoadPlacement] = []
    for item in resolved:
        assert item.size is not None
        rules_snapshot = deepcopy(item.rules)
        rules_snapshot["presentation"] = {
            "names": dict(item.names),
            "name_is_custom": item.name_is_custom,
        }
        if item.custom_template_id is not None:
            rules_snapshot["provenance"] = {
                "custom_template_id": str(item.custom_template_id),
                "template_revision": item.template_revision,
            }
        else:
            rules_snapshot["provenance"] = {"template_key": item.template_key}
        stored: StoredMonsterInstance = monster_repository.create_instance_in_transaction(
            connection,
            campaign_id=campaign_id,
            name=item.instance_name,
            rules_snapshot=rules_snapshot,
            template_key=item.template_key,
            custom_template_id=item.custom_template_id,
            instance_id=uuid4(),
            resources=initial_monster_resources(rules_snapshot),
            visibility=item.visibility,
            now=now,
        )
        footprint = footprint_for_size(item.size)
        entries.append(
            NewCombatEntry(
                subject_kind="monster",
                monster_instance_id=stored.id,
                display_name=stored.name,
            )
        )
        load_placements.append(
            MonsterLoadPlacement(
                anchor_x=item.anchor_x,
                anchor_y=item.anchor_y,
                footprint_width=footprint.width,
                footprint_height=footprint.height,
            )
        )
    return MonsterLoadOutcome(entries=tuple(entries), placements=tuple(load_placements))


__all__ = [
    "MonsterLoadOutcome",
    "MonsterLoadPlacement",
    "load_map_monsters",
]
