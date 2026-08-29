from __future__ import annotations

from uuid import UUID, uuid4

from sqlalchemy import (
    JSON,
    Column,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Table,
    Uuid,
    delete,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from app.db import metadata
from app.domain.character_builder.schemas import (
    BuilderDraft,
    BuilderDraftCreateInput,
    BuilderDraftPayload,
    BuilderMode,
)


json_payload_type = JSON().with_variant(JSONB(), "postgresql")

character_build_drafts = Table(
    "character_build_drafts",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("mode", String(32), nullable=False),
    Column("character_id", Uuid(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), nullable=True, index=True),
    Column("base_version_id", Uuid(as_uuid=True), ForeignKey("character_versions.id", ondelete="CASCADE"), nullable=True, index=True),
    Column("revision", Integer, nullable=False),
    Column("draft_payload", json_payload_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class BuilderDraftNotFoundError(LookupError):
    pass


class BuilderDraftRevisionConflictError(RuntimeError):
    def __init__(self, draft_id: UUID, expected_revision: int, actual_revision: int) -> None:
        super().__init__(
            f"draft {draft_id} revision mismatch: expected {expected_revision}, actual {actual_revision}"
        )
        self.draft_id = draft_id
        self.expected_revision = expected_revision
        self.actual_revision = actual_revision


class BuilderDraftRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    @staticmethod
    def _from_row(row) -> BuilderDraft:
        return BuilderDraft(
            id=row["id"],
            mode=BuilderMode(row["mode"]),
            character_id=row["character_id"],
            base_version_id=row["base_version_id"],
            revision=row["revision"],
            draft_payload=BuilderDraftPayload.model_validate(row["draft_payload"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def create_draft(self, request: BuilderDraftCreateInput) -> BuilderDraft:
        draft_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                insert(character_build_drafts).values(
                    id=draft_id,
                    mode=request.mode.value,
                    character_id=request.character_id,
                    base_version_id=request.base_version_id,
                    revision=1,
                    draft_payload=request.draft_payload.model_dump(mode="json"),
                )
            )
        return self.load_draft(draft_id)

    def list_drafts(self, *, mode: BuilderMode | None = None) -> tuple[BuilderDraft, ...]:
        query = select(character_build_drafts).order_by(character_build_drafts.c.updated_at.desc())
        if mode is not None:
            query = query.where(character_build_drafts.c.mode == mode.value)
        with self.engine.connect() as connection:
            rows = connection.execute(query).mappings().all()
        return tuple(self._from_row(row) for row in rows)

    def load_draft(self, draft_id: UUID) -> BuilderDraft:
        query = select(character_build_drafts).where(character_build_drafts.c.id == draft_id)
        with self.engine.connect() as connection:
            row = connection.execute(query).mappings().one_or_none()
        if row is None:
            raise BuilderDraftNotFoundError(str(draft_id))
        return self._from_row(row)

    def update_draft_payload(
        self,
        draft_id: UUID,
        *,
        expected_revision: int,
        draft_payload: BuilderDraftPayload,
    ) -> BuilderDraft:
        with self.engine.begin() as connection:
            result = connection.execute(
                update(character_build_drafts)
                .where(
                    character_build_drafts.c.id == draft_id,
                    character_build_drafts.c.revision == expected_revision,
                )
                .values(
                    revision=expected_revision + 1,
                    draft_payload=draft_payload.model_dump(mode="json"),
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                actual_revision = connection.scalar(
                    select(character_build_drafts.c.revision).where(character_build_drafts.c.id == draft_id)
                )
                if actual_revision is None:
                    raise BuilderDraftNotFoundError(str(draft_id))
                raise BuilderDraftRevisionConflictError(draft_id, expected_revision, int(actual_revision))
        return self.load_draft(draft_id)

    def delete_draft(self, draft_id: UUID) -> None:
        with self.engine.begin() as connection:
            result = connection.execute(
                delete(character_build_drafts).where(character_build_drafts.c.id == draft_id)
            )
            if result.rowcount != 1:
                raise BuilderDraftNotFoundError(str(draft_id))
