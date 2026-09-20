from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import insert, select
from sqlalchemy.engine import Connection, Engine, RowMapping

from app.persistence.campaign_runtime.tables import campaign_world_mutations


@dataclass(frozen=True)
class StoredCampaignWorldMutation:
    id: UUID
    campaign_id: UUID
    idempotency_key: str
    action_kind: str
    target_id: UUID | None
    command_payload: dict[str, object]
    result_payload: dict[str, object]
    created_by_actor_kind: str
    created_by_actor_id: UUID | None
    created_at: datetime


def _as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _row_to_stored_mutation(row: RowMapping) -> StoredCampaignWorldMutation:
    created_at = _as_utc(row["created_at"])
    assert created_at is not None
    return StoredCampaignWorldMutation(
        id=row["id"],
        campaign_id=row["campaign_id"],
        idempotency_key=row["idempotency_key"],
        action_kind=row["action_kind"],
        target_id=row["target_id"],
        command_payload=row["command_payload"],
        result_payload=row["result_payload"],
        created_by_actor_kind=row["created_by_actor_kind"],
        created_by_actor_id=row["created_by_actor_id"],
        created_at=created_at,
    )


class CampaignWorldMutationRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def get_in_transaction(
        connection: Connection,
        campaign_id: UUID,
        idempotency_key: str,
    ) -> StoredCampaignWorldMutation | None:
        query = select(campaign_world_mutations).where(
            campaign_world_mutations.c.campaign_id == campaign_id,
            campaign_world_mutations.c.idempotency_key == idempotency_key,
        )
        row = connection.execute(query).mappings().one_or_none()
        if row is None:
            return None
        return _row_to_stored_mutation(row)

    def get(
        self,
        campaign_id: UUID,
        idempotency_key: str,
    ) -> StoredCampaignWorldMutation | None:
        with self.engine.connect() as connection:
            return self.get_in_transaction(connection, campaign_id, idempotency_key)

    @staticmethod
    def insert_in_transaction(
        connection: Connection,
        mutation: StoredCampaignWorldMutation,
    ) -> None:
        connection.execute(
            insert(campaign_world_mutations).values(
                id=mutation.id,
                campaign_id=mutation.campaign_id,
                idempotency_key=mutation.idempotency_key,
                action_kind=mutation.action_kind,
                target_id=mutation.target_id,
                command_payload=mutation.command_payload,
                result_payload=mutation.result_payload,
                created_by_actor_kind=mutation.created_by_actor_kind,
                created_by_actor_id=mutation.created_by_actor_id,
                created_at=mutation.created_at,
            )
        )

    def insert(self, mutation: StoredCampaignWorldMutation) -> None:
        with self.engine.begin() as connection:
            self.insert_in_transaction(connection, mutation)


__all__ = [
    "CampaignWorldMutationRepository",
    "StoredCampaignWorldMutation",
]
