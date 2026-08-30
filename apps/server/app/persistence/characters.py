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
    UniqueConstraint,
    Uuid,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.engine import Engine

from app.content.registry import ContentRegistry
from app.db import metadata
from app.domain.character.schemas import CharacterBuild, CharacterState, PersistedCharacter
from app.domain.character.validation import validate_build_references, validate_state_against_build
from app.domain.character_builder.reconciliation import (
    StateReconciliationPreview,
    reconcile_character_state,
)
from app.domain.character_builder.versions import (
    CharacterVersionDetail,
    CharacterVersionKind,
    CharacterVersionSummary,
    build_version_summary,
)


json_payload_type = JSON().with_variant(JSONB(), "postgresql")

characters = Table(
    "characters",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("name", String(200), nullable=False),
    Column("ruleset", String(80), nullable=False),
    Column("current_version_id", Uuid(as_uuid=True), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)

character_versions = Table(
    "character_versions",
    metadata,
    Column("id", Uuid(as_uuid=True), primary_key=True),
    Column("character_id", Uuid(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), nullable=False, index=True),
    Column("version_no", Integer, nullable=False),
    Column("build_payload", json_payload_type, nullable=False),
    Column("version_kind", String(32), nullable=False, server_default="legacy"),
    Column(
        "parent_version_id",
        Uuid(as_uuid=True),
        ForeignKey("character_versions.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column(
        "superseded_by_version_id",
        Uuid(as_uuid=True),
        ForeignKey("character_versions.id", ondelete="SET NULL"),
        nullable=True,
    ),
    Column("change_note", String(500), nullable=True),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint("character_id", "version_no", name="uq_character_versions_character_version"),
)

character_states = Table(
    "character_states",
    metadata,
    Column("character_id", Uuid(as_uuid=True), ForeignKey("characters.id", ondelete="CASCADE"), primary_key=True),
    Column("state_payload", json_payload_type, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class CharacterNotFoundError(LookupError):
    pass


class CharacterVersionNotFoundError(LookupError):
    pass


class StaleBuildVersionError(RuntimeError):
    def __init__(
        self,
        character_id: UUID,
        expected_version_id: UUID,
        actual_version_id: UUID,
    ) -> None:
        super().__init__(
            f"character {character_id} build version changed: "
            f"expected {expected_version_id}, current {actual_version_id}"
        )
        self.character_id = character_id
        self.expected_version_id = expected_version_id
        self.actual_version_id = actual_version_id


class StateReconciliationBlockedError(RuntimeError):
    def __init__(self, preview: StateReconciliationPreview) -> None:
        message = (
            preview.blocking_issues[0].message
            if preview.blocking_issues
            else "state reconciliation is blocked"
        )
        super().__init__(message)
        self.preview = preview


class CharacterRepository:
    def __init__(self, engine: Engine, registry: ContentRegistry) -> None:
        self.engine = engine
        self.registry = registry

    def create_character(
        self,
        *,
        name: str,
        build: CharacterBuild,
        state: CharacterState,
        character_id: UUID | None = None,
        version_kind: str = "legacy",
    ) -> PersistedCharacter:
        if not name.strip():
            raise ValueError("character name cannot be blank")
        if build.ruleset != "dnd5e-2014":
            raise ValueError("P0 only supports dnd5e-2014")
        validate_build_references(build, self.registry)
        validate_state_against_build(state, build, self.registry)

        character_id = character_id or uuid4()
        version_id = uuid4()
        with self.engine.begin() as connection:
            connection.execute(
                insert(characters).values(
                    id=character_id,
                    name=name.strip(),
                    ruleset=build.ruleset,
                    current_version_id=None,
                )
            )
            connection.execute(
                insert(character_versions).values(
                    id=version_id,
                    character_id=character_id,
                    version_no=1,
                    build_payload=build.model_dump(mode="json"),
                    version_kind=version_kind,
                    parent_version_id=None,
                    superseded_by_version_id=None,
                    change_note=None,
                )
            )
            connection.execute(
                insert(character_states).values(
                    character_id=character_id,
                    state_payload=state.model_dump(mode="json"),
                )
            )
            connection.execute(
                update(characters)
                .where(characters.c.id == character_id)
                .values(current_version_id=version_id, updated_at=func.now())
            )
        return self.load_character(character_id)

    def create_character_from_builder_draft(
        self,
        *,
        draft_id: UUID,
        expected_revision: int,
        name: str,
        build: CharacterBuild,
        state: CharacterState,
    ) -> PersistedCharacter:
        """Atomically confirm a create draft.

        The draft row is locked in the same transaction that creates Character,
        immutable Version 1 and Current State. A repeated Confirm returns the
        already-created character instead of creating a duplicate.
        """

        from app.persistence.builder_drafts import (
            BuilderDraftNotFoundError,
            BuilderDraftRevisionConflictError,
            character_build_drafts,
        )

        if not name.strip():
            raise ValueError("character name cannot be blank")
        validate_build_references(build, self.registry)
        validate_state_against_build(state, build, self.registry)

        created_character_id: UUID | None = None
        existing_character_id: UUID | None = None
        with self.engine.begin() as connection:
            row = connection.execute(
                select(
                    character_build_drafts.c.id,
                    character_build_drafts.c.revision,
                    character_build_drafts.c.confirmed_character_id,
                )
                .where(character_build_drafts.c.id == draft_id)
                .with_for_update()
            ).mappings().one_or_none()
            if row is None:
                raise BuilderDraftNotFoundError(str(draft_id))

            if row["confirmed_character_id"] is not None:
                existing_character_id = row["confirmed_character_id"]
            else:
                actual_revision = int(row["revision"])
                if actual_revision != expected_revision:
                    raise BuilderDraftRevisionConflictError(
                        draft_id, expected_revision, actual_revision
                    )

                created_character_id = uuid4()
                version_id = uuid4()
                connection.execute(
                    insert(characters).values(
                        id=created_character_id,
                        name=name.strip(),
                        ruleset=build.ruleset,
                        current_version_id=None,
                    )
                )
                connection.execute(
                    insert(character_versions).values(
                        id=version_id,
                        character_id=created_character_id,
                        version_no=1,
                        build_payload=build.model_dump(mode="json"),
                        version_kind=CharacterVersionKind.CREATE.value,
                        parent_version_id=None,
                        superseded_by_version_id=None,
                        change_note=None,
                    )
                )
                connection.execute(
                    insert(character_states).values(
                        character_id=created_character_id,
                        state_payload=state.model_dump(mode="json"),
                    )
                )
                connection.execute(
                    update(characters)
                    .where(characters.c.id == created_character_id)
                    .values(current_version_id=version_id, updated_at=func.now())
                )
                connection.execute(
                    update(character_build_drafts)
                    .where(character_build_drafts.c.id == draft_id)
                    .values(
                        confirmed_character_id=created_character_id,
                        confirmed_version_id=version_id,
                        confirmed_at=func.now(),
                        updated_at=func.now(),
                    )
                )

        character_id = existing_character_id or created_character_id
        if character_id is None:
            raise RuntimeError("builder confirmation completed without a character id")
        return self.load_character(character_id)

    def create_build_version_from_builder_draft(
        self,
        *,
        draft_id: UUID,
        expected_revision: int,
        new_build: CharacterBuild,
        version_kind: CharacterVersionKind,
        change_note: str | None = None,
    ) -> tuple[PersistedCharacter, StateReconciliationPreview]:
        """Atomically append one immutable Build version and reconcile live state.

        The stale-base check intentionally happens inside this transaction, after
        the draft and character rows are locked. This is the authority boundary
        that prevents two drafts based on the same version from overwriting each
        other.
        """

        from app.persistence.builder_drafts import (
            BuilderDraftNotFoundError,
            BuilderDraftRevisionConflictError,
            character_build_drafts,
        )

        if version_kind not in {
            CharacterVersionKind.LEVEL_UP,
            CharacterVersionKind.BUILD_EDIT,
            CharacterVersionKind.CORRECTION,
        }:
            raise ValueError(f"invalid versioned builder kind: {version_kind.value}")
        validate_build_references(new_build, self.registry)

        created_character_id: UUID | None = None
        preview: StateReconciliationPreview | None = None
        with self.engine.begin() as connection:
            draft_row = connection.execute(
                select(
                    character_build_drafts.c.id,
                    character_build_drafts.c.mode,
                    character_build_drafts.c.character_id,
                    character_build_drafts.c.base_version_id,
                    character_build_drafts.c.revision,
                    character_build_drafts.c.confirmed_character_id,
                    character_build_drafts.c.confirmed_version_id,
                )
                .where(character_build_drafts.c.id == draft_id)
                .with_for_update()
            ).mappings().one_or_none()
            if draft_row is None:
                raise BuilderDraftNotFoundError(str(draft_id))
            if draft_row["confirmed_character_id"] is not None:
                existing = self.load_character(draft_row["confirmed_character_id"])
                # The state is not mutated on idempotent replay, but the caller's
                # response still needs a valid preview shape.
                current_preview = reconcile_character_state(
                    existing.build,
                    existing.state,
                    existing.build,
                    self.registry,
                )
                return existing, current_preview

            actual_revision = int(draft_row["revision"])
            if actual_revision != expected_revision:
                raise BuilderDraftRevisionConflictError(
                    draft_id, expected_revision, actual_revision
                )
            character_id = draft_row["character_id"]
            base_version_id = draft_row["base_version_id"]
            if character_id is None or base_version_id is None:
                raise ValueError("versioned builder draft requires character_id and base_version_id")

            current_row = connection.execute(
                select(
                    characters.c.current_version_id,
                    character_states.c.state_payload,
                )
                .join(character_states, character_states.c.character_id == characters.c.id)
                .where(characters.c.id == character_id)
                .with_for_update()
            ).mappings().one_or_none()
            if current_row is None or current_row["current_version_id"] is None:
                raise CharacterNotFoundError(str(character_id))
            actual_version_id = current_row["current_version_id"]
            if actual_version_id != base_version_id:
                raise StaleBuildVersionError(
                    character_id,
                    base_version_id,
                    actual_version_id,
                )

            base_row = connection.execute(
                select(
                    character_versions.c.version_no,
                    character_versions.c.build_payload,
                )
                .where(
                    character_versions.c.id == base_version_id,
                    character_versions.c.character_id == character_id,
                )
                .with_for_update()
            ).mappings().one_or_none()
            if base_row is None:
                raise CharacterVersionNotFoundError(str(base_version_id))

            old_build = CharacterBuild.model_validate(base_row["build_payload"])
            old_state = CharacterState.model_validate(current_row["state_payload"])
            preview = reconcile_character_state(
                old_build,
                old_state,
                new_build,
                self.registry,
            )
            if not preview.can_apply:
                raise StateReconciliationBlockedError(preview)
            validate_state_against_build(preview.proposed_state, new_build, self.registry)

            new_version_id = uuid4()
            new_version_no = int(base_row["version_no"]) + 1
            connection.execute(
                insert(character_versions).values(
                    id=new_version_id,
                    character_id=character_id,
                    version_no=new_version_no,
                    build_payload=new_build.model_dump(mode="json"),
                    version_kind=version_kind.value,
                    parent_version_id=base_version_id,
                    superseded_by_version_id=None,
                    change_note=change_note,
                )
            )
            if version_kind is CharacterVersionKind.CORRECTION:
                connection.execute(
                    update(character_versions)
                    .where(character_versions.c.id == base_version_id)
                    .values(superseded_by_version_id=new_version_id)
                )
            connection.execute(
                update(characters)
                .where(characters.c.id == character_id)
                .values(current_version_id=new_version_id, updated_at=func.now())
            )
            connection.execute(
                update(character_states)
                .where(character_states.c.character_id == character_id)
                .values(
                    state_payload=preview.proposed_state.model_dump(mode="json"),
                    updated_at=func.now(),
                )
            )
            connection.execute(
                update(character_build_drafts)
                .where(character_build_drafts.c.id == draft_id)
                .values(
                    confirmed_character_id=character_id,
                    confirmed_version_id=new_version_id,
                    confirmed_at=func.now(),
                    updated_at=func.now(),
                )
            )
            created_character_id = character_id

        if created_character_id is None or preview is None:
            raise RuntimeError("version confirmation completed without a result")
        return self.load_character(created_character_id), preview

    def list_characters(self) -> tuple[PersistedCharacter, ...]:
        with self.engine.connect() as connection:
            ids = connection.scalars(select(characters.c.id).order_by(characters.c.name, characters.c.id)).all()
        return tuple(self.load_character(character_id) for character_id in ids)

    def load_character(self, character_id: UUID) -> PersistedCharacter:
        query = (
            select(
                characters.c.id,
                characters.c.name,
                characters.c.ruleset,
                characters.c.current_version_id,
                character_versions.c.version_no,
                character_versions.c.build_payload,
                character_states.c.state_payload,
            )
            .join(character_versions, character_versions.c.id == characters.c.current_version_id)
            .join(character_states, character_states.c.character_id == characters.c.id)
            .where(characters.c.id == character_id)
        )
        with self.engine.connect() as connection:
            row = connection.execute(query).mappings().one_or_none()
        if row is None:
            raise CharacterNotFoundError(str(character_id))

        build = CharacterBuild.model_validate(row["build_payload"])
        state = CharacterState.model_validate(row["state_payload"])
        validate_build_references(build, self.registry)
        validate_state_against_build(state, build, self.registry)
        return PersistedCharacter(
            id=row["id"],
            name=row["name"],
            ruleset=row["ruleset"],
            current_version_id=row["current_version_id"],
            version_no=row["version_no"],
            build=build,
            state=state,
        )

    def load_build_version(self, character_id: UUID, version_id: UUID) -> CharacterBuild:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(character_versions.c.build_payload).where(
                    character_versions.c.id == version_id,
                    character_versions.c.character_id == character_id,
                )
            ).mappings().one_or_none()
        if row is None:
            raise CharacterVersionNotFoundError(str(version_id))
        return CharacterBuild.model_validate(row["build_payload"])

    def list_versions(self, character_id: UUID) -> tuple[CharacterVersionSummary, ...]:
        with self.engine.connect() as connection:
            character_row = connection.execute(
                select(characters.c.current_version_id).where(characters.c.id == character_id)
            ).mappings().one_or_none()
            if character_row is None or character_row["current_version_id"] is None:
                raise CharacterNotFoundError(str(character_id))
            rows = connection.execute(
                select(character_versions)
                .where(character_versions.c.character_id == character_id)
                .order_by(character_versions.c.version_no)
            ).mappings().all()
        return tuple(
            build_version_summary(
                version_id=row["id"],
                character_id=row["character_id"],
                version_no=int(row["version_no"]),
                version_kind=row["version_kind"],
                parent_version_id=row["parent_version_id"],
                superseded_by_version_id=row["superseded_by_version_id"],
                change_note=row["change_note"],
                created_at=row["created_at"],
                current_version_id=character_row["current_version_id"],
                build=CharacterBuild.model_validate(row["build_payload"]),
                registry=self.registry,
            )
            for row in rows
        )

    def load_version(self, character_id: UUID, version_no: int) -> CharacterVersionDetail:
        with self.engine.connect() as connection:
            character_row = connection.execute(
                select(characters.c.current_version_id).where(characters.c.id == character_id)
            ).mappings().one_or_none()
            if character_row is None or character_row["current_version_id"] is None:
                raise CharacterNotFoundError(str(character_id))
            row = connection.execute(
                select(character_versions).where(
                    character_versions.c.character_id == character_id,
                    character_versions.c.version_no == version_no,
                )
            ).mappings().one_or_none()
        if row is None:
            raise CharacterVersionNotFoundError(f"{character_id}/v{version_no}")
        build = CharacterBuild.model_validate(row["build_payload"])
        summary = build_version_summary(
            version_id=row["id"],
            character_id=row["character_id"],
            version_no=int(row["version_no"]),
            version_kind=row["version_kind"],
            parent_version_id=row["parent_version_id"],
            superseded_by_version_id=row["superseded_by_version_id"],
            change_note=row["change_note"],
            created_at=row["created_at"],
            current_version_id=character_row["current_version_id"],
            build=build,
            registry=self.registry,
        )
        return CharacterVersionDetail(**summary.model_dump(mode="python"), build=build)

    def save_state(self, character_id: UUID, state: CharacterState) -> PersistedCharacter:
        current = self.load_character(character_id)
        validate_state_against_build(state, current.build, self.registry)
        with self.engine.begin() as connection:
            result = connection.execute(
                update(character_states)
                .where(character_states.c.character_id == character_id)
                .values(state_payload=state.model_dump(mode="json"), updated_at=func.now())
            )
            if result.rowcount != 1:
                raise CharacterNotFoundError(str(character_id))
            connection.execute(
                update(characters)
                .where(characters.c.id == character_id)
                .values(updated_at=func.now())
            )
        return self.load_character(character_id)
