from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from uuid import UUID

from sqlalchemy import select, update
from sqlalchemy.engine import Engine

from app.persistence.combat.lifecycle import CombatNotFoundPersistenceError
from app.persistence.combat.repository import (
    _UNSET,
    StoredMonsterInstance,
    _instance_from_row,
)
from app.persistence.combat.tables import (
    combat_entries,
    combats,
    monster_instances,
)
from app.persistence.rooms.table_runtime import (
    StoredTableActorBinding,
    StoredTableEvent,
    TableEventRepository,
    session_events,
)


class MonsterBookkeepingRepository:
    def __init__(self, engine: Engine, event_repository: TableEventRepository) -> None:
        self.engine = engine
        self.event_repository = event_repository

    def get_instance(self, instance_id: UUID) -> StoredMonsterInstance:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(monster_instances).where(monster_instances.c.id == instance_id)
            ).mappings().one_or_none()
        if row is None:
            raise CombatNotFoundPersistenceError(f"monster instance not found: {instance_id}")
        return _instance_from_row(row)

    def update_instance(
        self,
        *,
        binding: StoredTableActorBinding,
        instance_id: UUID,
        name: str | None | object = _UNSET,
        visibility: str | None | object = _UNSET,
        position_note: str | None | object = _UNSET,
        reveal_patch: dict[str, bool] | None = None,
        idempotency_key: str | None = None,
    ) -> tuple[StoredMonsterInstance, StoredTableEvent]:
        prefix_key = f"p4f-monster-update:{idempotency_key}" if idempotency_key else None

        def projection(connection: Any, event_id: UUID, _seq: int) -> None:
            instance_row = connection.execute(
                select(monster_instances)
                .where(
                    monster_instances.c.id == instance_id,
                    monster_instances.c.campaign_id == binding.campaign_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if instance_row is None:
                raise CombatNotFoundPersistenceError(f"monster instance not found: {instance_id}")

            current_reveal = dict(instance_row["reveal_state"] or {})
            if reveal_patch:
                current_reveal.update(reveal_patch)

            changed_fields: list[str] = []
            instance_updates: dict[str, Any] = {
                "updated_at": datetime.now(timezone.utc),
            }

            if name is not _UNSET and name is not None:
                new_name = str(name).strip()
                instance_updates["name"] = new_name
                changed_fields.append("name")
            else:
                new_name = instance_row["name"]

            if visibility is not _UNSET and visibility is not None:
                instance_updates["visibility"] = visibility
                changed_fields.append("visibility")

            if position_note is not _UNSET:
                instance_updates["position_note"] = position_note
                changed_fields.append("position_note")

            if reveal_patch:
                instance_updates["reveal_state"] = current_reveal
                changed_fields.append("reveal")

            active_combat = connection.execute(
                select(combats)
                .where(
                    combats.c.campaign_id == binding.campaign_id,
                    combats.c.status.in_(("initiative_pending", "running")),
                )
                .with_for_update()
            ).mappings().one_or_none()

            combat_entry_id: UUID | None = None
            if active_combat is not None:
                entry_row = connection.execute(
                    select(combat_entries)
                    .where(
                        combat_entries.c.combat_id == active_combat["id"],
                        combat_entries.c.monster_instance_id == instance_id,
                        combat_entries.c.status == "active",
                    )
                    .with_for_update()
                ).mappings().one_or_none()
                if entry_row is not None:
                    combat_entry_id = entry_row["id"]
                    if name is not _UNSET and name is not None and new_name != instance_row["name"]:
                        connection.execute(
                            update(combat_entries)
                            .where(combat_entries.c.id == entry_row["id"])
                            .values(
                                display_name=new_name,
                                updated_at=datetime.now(timezone.utc),
                            )
                        )
                        connection.execute(
                            update(combats)
                            .where(combats.c.id == active_combat["id"])
                            .values(
                                revision=combats.c.revision + 1,
                                updated_at=datetime.now(timezone.utc),
                            )
                        )

            connection.execute(
                update(monster_instances)
                .where(monster_instances.c.id == instance_id)
                .values(**instance_updates)
            )

            final_payload = {
                "monster_instance_id": str(instance_id),
                "combat_entry_id": str(combat_entry_id) if combat_entry_id is not None else None,
                "name": instance_updates.get("name", instance_row["name"]),
                "visibility": instance_updates.get("visibility", instance_row["visibility"]),
                "changed": changed_fields,
                "reveal": {
                    "armor_class": bool(current_reveal.get("armor_class", False)),
                    "description": bool(current_reveal.get("description", False)),
                    "position_note": bool(current_reveal.get("position_note", False)),
                },
            }

            connection.execute(
                update(session_events)
                .where(session_events.c.id == event_id)
                .values(payload=final_payload)
            )

        event = self.event_repository.append(
            room_id=binding.room_id,
            campaign_id=binding.campaign_id,
            session_id=binding.session_id,
            kind="combat.monster_instance_updated",
            acting_seat_id=binding.seat_id,
            subject_seat_id=None,
            subject_character_id=None,
            execution_mode="self",
            visibility="public",
            recipient_seat_ids=(),
            payload_version=1,
            payload={
                "monster_instance_id": str(instance_id),
                "combat_entry_id": None,
                "name": "",
                "visibility": "",
                "changed": [],
                "reveal": {
                    "armor_class": False,
                    "description": False,
                    "position_note": False,
                },
            },
            idempotency_key=prefix_key,
            expected_actor_binding=binding,
            transaction_projection=projection,
        )

        canonical_instance_id = UUID(str(event.payload["monster_instance_id"]))
        stored = self.get_instance(canonical_instance_id)
        return stored, event


__all__ = ["MonsterBookkeepingRepository"]
