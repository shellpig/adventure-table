from __future__ import annotations

from uuid import UUID

from sqlalchemy import func, or_, select
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
from app.persistence.campaign_runtime.tables import (
    campaign_adventure_overrides,
    campaign_world_entries,
    campaign_world_mutations,
)
from app.persistence.combat.tables import monster_instances, monster_templates
from app.persistence.rooms.tables import campaigns


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
    (unless previous_ref == ref, in which case an unchanged archived reference is permitted).
    Returns the parsed template UUID, or None if ref is not a custom template ref.
    """
    if ref is None:
        return None
    normalized_ref = ref.strip()
    if not normalized_ref.startswith("custom:"):
        return None

    raw_uuid = normalized_ref.removeprefix("custom:").strip()
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
    if previous_ref is not None and previous_ref.strip() == normalized_ref:
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

    Scans:
    - monster_instances.custom_template_id
    - adventure_entries (npc, monster_ref)
    - campaign_world_entries (npc)
    - campaign_adventure_overrides
    - adventure_import_drafts
    """
    ref_str = f"custom:{template_id}"

    # 1. monster_instances
    inst_count = connection.scalar(
        select(func.count())
        .select_from(monster_instances)
        .where(monster_instances.c.custom_template_id == template_id)
    )
    if inst_count and inst_count > 0:
        return True

    # 2. adventure_entries
    adv_count = connection.scalar(
        select(func.count())
        .select_from(
            adventure_entries.join(
                adventure_definitions,
                adventure_entries.c.adventure_id == adventure_definitions.c.id,
            )
        )
        .where(
            adventure_definitions.c.room_id == room_id,
            adventure_entries.c.kind.in_(("npc", "monster_ref")),
            adventure_entries.c.data_json["monster_template_ref"].as_string() == ref_str,
        )
    )
    if adv_count and adv_count > 0:
        return True

    # 3. campaign_world_entries
    world_count = connection.scalar(
        select(func.count())
        .select_from(
            campaign_world_entries.join(
                campaigns,
                campaign_world_entries.c.campaign_id == campaigns.c.id,
            )
        )
        .where(
            campaigns.c.room_id == room_id,
            campaign_world_entries.c.kind == "npc",
            campaign_world_entries.c.state_json["monster_template_ref"].as_string() == ref_str,
        )
    )
    if world_count and world_count > 0:
        return True

    # 4. campaign_adventure_overrides
    override_count = connection.scalar(
        select(func.count())
        .select_from(
            campaign_adventure_overrides.join(
                campaigns,
                campaign_adventure_overrides.c.campaign_id == campaigns.c.id,
            )
        )
        .where(
            campaigns.c.room_id == room_id,
            campaign_adventure_overrides.c.state_json["monster_template_ref"].as_string() == ref_str,
        )
    )
    if override_count and override_count > 0:
        return True

    # 5. campaign_world_mutations (durable mutation typed provenance)
    mutation_count = connection.scalar(
        select(func.count())
        .select_from(
            campaign_world_mutations.join(
                campaigns,
                campaign_world_mutations.c.campaign_id == campaigns.c.id,
            )
        )
        .where(
            campaigns.c.room_id == room_id,
            or_(
                campaign_world_mutations.c.command_payload["state"]["monster_template_ref"].as_string() == ref_str,
                campaign_world_mutations.c.result_payload["state"]["monster_template_ref"].as_string() == ref_str,
            ),
        )
    )
    if mutation_count and mutation_count > 0:
        return True

    # 6. adventure_import_drafts
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
                            and payload.get("monster_template_ref") == ref_str
                        ):
                            return True

    return False
