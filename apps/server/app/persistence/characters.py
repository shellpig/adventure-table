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
    Column(
        "character_id",
        Uuid(as_uuid=True),
        ForeignKey("characters.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    ),
    Column("version_no", Integer, nullable=False),
    Column("build_payload", json_payload_type, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
    UniqueConstraint(
        "character_id",
        "version_no",
        name="uq_character_versions_character_version",
    ),
)

character_states = Table(
    "character_states",
    metadata,
    Column(
        "character_id",
        Uuid(as_uuid=True),
        ForeignKey("characters.id", ondelete="CASCADE"),
        primary_key=True,
    ),
    Column("state_payload", json_payload_type, nullable=False),
    Column("updated_at", DateTime(timezone=True), nullable=False, server_default=func.now()),
)


class CharacterNotFoundError(LookupError):
    pass


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
            .join(
                character_versions,
                character_versions.c.id == characters.c.current_version_id,
            )
            .join(
                character_states,
                character_states.c.character_id == characters.c.id,
            )
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

    def save_state(self, character_id: UUID, state: CharacterState) -> PersistedCharacter:
        current = self.load_character(character_id)
        validate_state_against_build(state, current.build, self.registry)

        with self.engine.begin() as connection:
            result = connection.execute(
                update(character_states)
                .where(character_states.c.character_id == character_id)
                .values(
                    state_payload=state.model_dump(mode="json"),
                    updated_at=func.now(),
                )
            )
            if result.rowcount != 1:
                raise CharacterNotFoundError(str(character_id))
            connection.execute(
                update(characters)
                .where(characters.c.id == character_id)
                .values(updated_at=func.now())
            )

        return self.load_character(character_id)
