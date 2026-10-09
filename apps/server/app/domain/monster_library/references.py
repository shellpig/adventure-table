from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.engine import Connection

from app.domain.monster_library.errors import (
    InvalidMonsterTemplateRefError,
    MonsterTemplateArchivedError,
    MonsterTemplateNotFoundError,
)
from app.persistence.adventure_imports.tables import (
    adventure_import_drafts,
    adventure_imports,
)
from app.persistence.adventures.tables import (
    adventure_definitions,
    adventure_entries,
)
from app.persistence.battle_maps.tables import (
    battle_map_monster_placements,
    battle_maps,
)
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_world_entries,
    campaign_world_mutations,
)
from app.persistence.combat.tables import monster_instances, monster_templates
from app.persistence.rooms.tables import campaigns


_CUSTOM_PREFIX = "custom:"


def _split_custom_prefix(ref: str) -> str | None:
    """Split the ``custom:`` scheme prefix case-insensitively.

    The scheme itself is always stored lowercase; accepting ``CUSTOM:`` /
    ``Custom:`` spellings on input keeps non-standard client spellings from
    slipping past validation as opaque built-in keys.
    """
    text = ref.strip()
    if text[: len(_CUSTOM_PREFIX)].casefold() != _CUSTOM_PREFIX:
        return None
    return text[len(_CUSTOM_PREFIX) :].strip()


def normalize_monster_template_ref(ref: str | None) -> str | None:
    """Canonicalize a stored monster template reference (M07-D D1 F04).

    ``custom:`` refs become ``custom:<lowercase UUID>`` so the deletion
    reference scan cannot be bypassed by non-standard spellings (uppercase
    hex or scheme, surrounding whitespace). Non-custom refs (built-in
    content keys) are returned stripped but otherwise untouched.
    Unparseable ``custom:`` values are returned stripped; format errors stay
    the job of :func:`validate_custom_monster_template_ref`.
    """
    if ref is None:
        return None
    raw_uuid = _split_custom_prefix(ref)
    if raw_uuid is None:
        return ref.strip()
    try:
        template_id = UUID(raw_uuid)
    except ValueError:
        return ref.strip()
    return f"{_CUSTOM_PREFIX}{template_id}"


def canonicalize_state_monster_ref(state: dict[str, object] | None) -> dict[str, object] | None:
    """Return a copy of a raw entry-state dict with a canonical ``custom:`` ref (M07-D D1 F04).

    Typed payload models normalize on parse, but Runtime/override states are
    stored as raw dicts, so write sites pass the dict through here before
    persisting. Dicts without a ``monster_template_ref`` are returned as-is.
    """
    if not isinstance(state, dict):
        return state
    ref = state.get("monster_template_ref")
    if not isinstance(ref, str) or not ref.strip():
        return state
    canonical = normalize_monster_template_ref(ref)
    if canonical == ref:
        return state
    copied = dict(state)
    copied["monster_template_ref"] = canonical
    return copied


def _parse_custom_ref_id(ref: object) -> UUID | None:
    """Parse any spelling of a ``custom:`` ref to its template UUID."""
    if not isinstance(ref, str):
        return None
    raw_uuid = _split_custom_prefix(ref)
    if raw_uuid is None:
        return None
    try:
        return UUID(raw_uuid)
    except ValueError:
        return None


def validate_custom_monster_template_ref(
    connection: Connection,
    *,
    room_id: UUID,
    ref: str | None,
    previous_ref: str | None = None,
) -> UUID | None:
    """Validate a monster template reference.

    If ref starts with 'custom:<uuid>', locks the template row with FOR UPDATE,
    verifies it belongs to the given room, and checks that it is not archived
    (unless previous_ref names the same template, in which case an unchanged
    archived reference is permitted; both spellings are canonicalized before
    comparing so legacy non-standard UUID spellings still match).
    Returns the parsed template UUID, or None if ref is not a custom template ref.
    """
    if ref is None:
        return None
    normalized_ref = normalize_monster_template_ref(ref)
    assert normalized_ref is not None
    if not normalized_ref.startswith("custom:"):
        return None

    raw_uuid = normalized_ref.removeprefix("custom:")
    try:
        template_id = UUID(raw_uuid)
    except ValueError as exc:
        raise InvalidMonsterTemplateRefError(
            f"invalid custom monster template ref format: '{ref}'"
        ) from exc

    stmt = (
        select(
            monster_templates.c.id,
            monster_templates.c.room_id,
            monster_templates.c.archived_at,
        )
        .where(monster_templates.c.id == template_id)
        .with_for_update()
    )
    row = connection.execute(stmt).mappings().first()
    if row is None or row["room_id"] != room_id:
        raise MonsterTemplateNotFoundError(
            f"monster template '{template_id}' not found in room '{room_id}'"
        )

    # Unchanged archived references are allowed to stay
    if previous_ref is not None and normalize_monster_template_ref(previous_ref) == normalized_ref:
        return template_id

    if row["archived_at"] is not None:
        raise MonsterTemplateArchivedError(
            f"monster template '{template_id}' is archived"
        )

    return template_id


def is_monster_template_referenced(
    connection: Connection,
    *,
    room_id: UUID,
    template_id: UUID,
) -> bool:
    """Scan all typed references to a custom monster template within the room.

    Stored ``custom:`` refs are parsed to UUIDs before comparing (M07-D D1
    F04), so legacy rows with non-standard UUID spellings (uppercase hex,
    extra whitespace) still block deletion. New writes are canonicalized to
    ``custom:<lowercase UUID>`` at the payload layer; the tolerant scan keeps
    pre-existing rows safe without a data migration.

    Scans:
    - monster_instances.custom_template_id
    - battle_map_monster_placements.custom_template_id (M07-C)
    - adventure_entries (npc, monster_ref)
    - campaign_world_entries (npc)
    - campaign_adventure_overrides
    - adventure_import_drafts
    """
    def _matches(ref: object) -> bool:
        return _parse_custom_ref_id(ref) == template_id

    # 1. monster_instances
    inst_count = connection.scalar(
        select(func.count())
        .select_from(monster_instances)
        .where(monster_instances.c.custom_template_id == template_id)
    )
    if inst_count and inst_count > 0:
        return True

    # 2. battle_map_monster_placements (M07-C map pre-placements)
    placement_count = connection.scalar(
        select(func.count())
        .select_from(
            battle_map_monster_placements.join(
                battle_maps,
                battle_map_monster_placements.c.battle_map_id == battle_maps.c.id,
            )
        )
        .where(
            battle_maps.c.room_id == room_id,
            battle_map_monster_placements.c.custom_template_id == template_id,
        )
    )
    if placement_count and placement_count > 0:
        return True

    # 3. adventure_entries (JSON refs compared by parsed UUID, not spelling)
    adv_refs = connection.scalars(
        select(adventure_entries.c.data_json["monster_template_ref"].as_string())
        .select_from(
            adventure_entries.join(
                adventure_definitions,
                adventure_entries.c.adventure_id == adventure_definitions.c.id,
            )
        )
        .where(
            adventure_definitions.c.room_id == room_id,
            adventure_entries.c.kind.in_(("npc", "monster_ref")),
        )
    ).all()
    if any(_matches(ref) for ref in adv_refs):
        return True

    # 4. campaign_world_entries
    world_refs = connection.scalars(
        select(campaign_world_entries.c.state_json["monster_template_ref"].as_string())
        .select_from(
            campaign_world_entries.join(
                campaigns,
                campaign_world_entries.c.campaign_id == campaigns.c.id,
            )
        )
        .where(
            campaigns.c.room_id == room_id,
            campaign_world_entries.c.kind == "npc",
        )
    ).all()
    if any(_matches(ref) for ref in world_refs):
        return True

    # 5. campaign_adventure_overrides
    override_refs = connection.scalars(
        select(campaign_adventure_overrides.c.state_json["monster_template_ref"].as_string())
        .select_from(
            campaign_adventure_overrides.join(
                campaigns,
                campaign_adventure_overrides.c.campaign_id == campaigns.c.id,
            )
        )
        .where(campaigns.c.room_id == room_id)
    ).all()
    if any(_matches(ref) for ref in override_refs):
        return True

    # 6. campaign_world_mutations (durable mutation typed provenance)
    mutation_rows = connection.execute(
        select(
            campaign_world_mutations.c.command_payload["state"]["monster_template_ref"].as_string(),
            campaign_world_mutations.c.result_payload["state"]["monster_template_ref"].as_string(),
        )
        .select_from(
            campaign_world_mutations.join(
                campaigns,
                campaign_world_mutations.c.campaign_id == campaigns.c.id,
            )
        )
        .where(campaigns.c.room_id == room_id)
    ).all()
    if any(_matches(value) for row in mutation_rows for value in tuple(row)):
        return True

    # 7. adventure_import_drafts
    draft_rows = connection.scalars(
        select(adventure_import_drafts.c.draft_json)
        .select_from(
            adventure_import_drafts.join(
                adventure_imports,
                adventure_import_drafts.c.import_id == adventure_imports.c.id,
            )
        )
        .where(adventure_imports.c.room_id == room_id)
    ).all()
    for draft_data in draft_rows:
        if isinstance(draft_data, dict):
            entries = draft_data.get("entries")
            if isinstance(entries, list):
                for entry in entries:
                    if isinstance(entry, dict):
                        payload = entry.get("payload")
                        if (
                            isinstance(payload, dict)
                            and _matches(payload.get("monster_template_ref"))
                        ):
                            return True

    return False


__all__ = [
    "canonicalize_state_monster_ref",
    "is_monster_template_referenced",
    "normalize_monster_template_ref",
    "validate_custom_monster_template_ref",
]
