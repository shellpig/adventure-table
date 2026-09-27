"""P5-F read-only tactical target check (backend only).

Wraps the P5-C spatial targeting primitives (``validate_attack_target``,
``validate_spell_target``, ``public_blocker_kind``) so Human REST and MCP
share the exact same geometry as ``combat_request_attack`` /
``combat_cast_spell``. No state is changed and no events are emitted; an
illegal target is reported as data, never raised.

Attack resolution reuses ``AttackDefinitionResolver.resolve`` (the same call
``CombatAttackService`` uses for ``source_ref``). Spell range reuses the
content-registry ``range`` text plus ``parse_spell_range`` (the same data path
``CombatSpellService._validate_tactical_spell_target`` builds on); slot /
preparation authorization is intentionally out of scope for a geometry check.
"""

from __future__ import annotations

from typing import Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.content.registry import ContentRegistry
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.board import CombatBoardService
from app.domain.combat.lifecycle import (
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
)
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import TableActorContext, TableEventService
from app.domain.spatial.pathing import grid_distance
from app.domain.spatial.targeting import (
    parse_spell_range,
    validate_attack_target,
    validate_spell_target,
)
from app.persistence.combat.lifecycle import CombatRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.resolution import CombatResolutionTargetNotFoundError


class TargetCheckInput(StrictModel):
    """Exactly one of ``attack_source_ref`` / ``spell_ref`` selects the range."""

    source_entry_id: UUID
    target_entry_id: UUID
    attack_source_ref: str | None = Field(default=None, min_length=1, max_length=320)
    spell_ref: str | None = Field(default=None, min_length=1, max_length=320)

    @model_validator(mode="after")
    def _exactly_one_ref(self) -> TargetCheckInput:
        if (self.attack_source_ref is None) == (self.spell_ref is None):
            raise ValueError(
                "exactly one of attack_source_ref / spell_ref is required"
            )
        return self


class TargetCheckResult(StrictModel):
    source_entry_id: UUID
    target_entry_id: UUID
    kind: Literal["attack", "spell"]
    ref: str
    legal: bool
    in_range: bool
    distance_feet: int | None
    range_band: str
    blocked: bool
    blocker_kind: str | None
    requires_dm_adjudication: bool
    is_long_range: bool
    target_within_5ft: bool


class TargetCheckService:
    """Read-only tactical range/blocker check for attacks and targeted spells."""

    def __init__(
        self,
        *,
        table_event_service: TableEventService,
        combat_service: CombatService,
        board_service: CombatBoardService,
        attack_definition_resolver: AttackDefinitionResolver,
        monster_repository: MonsterRepository,
        registry: ContentRegistry,
    ) -> None:
        self.table_event_service = table_event_service
        self.combat_service = combat_service
        self.board_service = board_service
        self.attack_definition_resolver = attack_definition_resolver
        self.monster_repository = monster_repository
        self.registry = registry

    @property
    def _combat_repository(self) -> CombatRepository:
        return self.combat_service.repository

    def _tactical_combat_id(self, actor: TableActorContext) -> UUID:
        self.table_event_service.require_actor_current(actor)
        combat = self._combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        if combat.mode != "tactical":
            raise CombatStateConflictError("Target check requires Tactical Combat")
        return combat.id

    def _active_entry(self, combat_id: UUID, entry_id: UUID):
        entry = self._combat_repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat_id or entry.status != "active":
            raise CombatNotFoundError("Combat entry is missing or inactive")
        return entry

    def _reject_hidden_target_for_player(
        self, actor: TableActorContext, target
    ) -> None:
        """P5-C: players cannot target hidden monsters at all."""
        if actor.is_current_dm:
            return
        if target.subject_kind != "monster" or target.monster_instance_id is None:
            return
        instance = self.monster_repository.get_instance(target.monster_instance_id)
        if instance is not None and instance.visibility == "hidden":
            raise CombatResolutionTargetNotFoundError("Combat target is not visible")

    def check_target(
        self, actor: TableActorContext, input: TargetCheckInput
    ) -> TargetCheckResult:
        combat_id = self._tactical_combat_id(actor)
        source = self._active_entry(combat_id, input.source_entry_id)
        target = self._active_entry(combat_id, input.target_entry_id)
        # A Player may only check targets for entries they control; the DM may
        # check any entry. Mirrors movement preview authorization.
        self.combat_service._authorize_entry(actor, source)
        self._reject_hidden_target_for_player(actor, target)

        source_cells = self.board_service.entry_footprint_cells(source)
        target_cells = self.board_service.entry_footprint_cells(target)
        barriers = self.board_service.sight_barriers(combat_id)
        audience = "dm" if actor.is_current_dm else "player"

        if input.attack_source_ref is not None:
            attack = self.attack_definition_resolver.resolve(
                source, input.attack_source_ref
            )
            result = validate_attack_target(
                source_cells=source_cells,
                target_cells=target_cells,
                attack=attack,
                barriers=barriers,
                audience=audience,
            )
            return TargetCheckResult(
                source_entry_id=source.id,
                target_entry_id=target.id,
                kind="attack",
                ref=input.attack_source_ref,
                legal=result.legal,
                in_range=result.range_band in ("reach", "normal", "long"),
                distance_feet=result.distance_feet,
                range_band=result.range_band,
                blocked=result.blocked,
                blocker_kind=result.blocker_kind,
                requires_dm_adjudication=result.requires_dm_adjudication,
                is_long_range=result.is_long_range,
                target_within_5ft=result.target_within_5ft,
            )

        assert input.spell_ref is not None
        spell_entry = self.registry.get(input.spell_ref)
        spell_data = spell_entry.data
        range_text = (
            spell_data.get("range")
            if isinstance(spell_data.get("range"), str)
            else None
        )
        kind, feet = parse_spell_range(range_text)
        if kind == "self":
            is_self = target.id == source.id
            return TargetCheckResult(
                source_entry_id=source.id,
                target_entry_id=target.id,
                kind="spell",
                ref=input.spell_ref,
                legal=is_self,
                in_range=is_self,
                distance_feet=0,
                range_band="normal" if is_self else "out_of_range",
                blocked=False,
                blocker_kind=None,
                requires_dm_adjudication=False,
                is_long_range=False,
                target_within_5ft=True,
            )
        if kind == "unknown" or feet is None:
            distance = grid_distance(source_cells, target_cells)
            return TargetCheckResult(
                source_entry_id=source.id,
                target_entry_id=target.id,
                kind="spell",
                ref=input.spell_ref,
                legal=False,
                in_range=False,
                distance_feet=distance.feet,
                range_band="unknown",
                blocked=False,
                blocker_kind=None,
                requires_dm_adjudication=True,
                is_long_range=False,
                target_within_5ft=distance.feet <= 5,
            )
        result = validate_spell_target(
            source_cells=source_cells,
            target_cells=target_cells,
            range_feet=feet,
            barriers=barriers,
            audience=audience,
        )
        return TargetCheckResult(
            source_entry_id=source.id,
            target_entry_id=target.id,
            kind="spell",
            ref=input.spell_ref,
            legal=result.legal,
            in_range=result.range_band == "normal",
            distance_feet=result.distance_feet,
            range_band=result.range_band,
            blocked=result.blocked,
            blocker_kind=result.blocker_kind,
            requires_dm_adjudication=result.requires_dm_adjudication,
            is_long_range=result.is_long_range,
            target_within_5ft=result.target_within_5ft,
        )


__all__ = [
    "TargetCheckInput",
    "TargetCheckResult",
    "TargetCheckService",
]
