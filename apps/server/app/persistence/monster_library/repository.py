from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import delete, insert, select, update
from sqlalchemy.engine import Connection, Engine

from app.domain.monster_library.errors import (
    MonsterTemplateNotFoundError,
    MonsterTemplateRevisionConflictError,
)
from app.persistence.combat.repository import StoredMonsterTemplate, _template_from_row
from app.persistence.combat.tables import monster_templates


class MonsterLibraryRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def list_custom_templates(
        self,
        room_id: UUID,
        *,
        include_archived: bool = False,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
        connection: Connection | None = None,
    ) -> tuple[StoredMonsterTemplate, ...]:
        stmt = select(monster_templates).where(monster_templates.c.room_id == room_id)
        if not include_archived:
            stmt = stmt.where(monster_templates.c.archived_at.is_(None))
        if query is not None and query.strip():
            stmt = stmt.where(monster_templates.c.name.ilike(f"%{query.strip()}%"))
        stmt = stmt.order_by(monster_templates.c.name, monster_templates.c.id).limit(limit).offset(offset)

        if connection is not None:
            rows = connection.execute(stmt).mappings().all()
            return tuple(_template_from_row(row) for row in rows)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return tuple(_template_from_row(row) for row in rows)

    def list_custom_templates_for_search(
        self,
        room_id: UUID,
        *,
        include_archived: bool = False,
        connection: Connection | None = None,
    ) -> tuple[StoredMonsterTemplate, ...]:
        """Fetch every custom template of a room for Python-side query matching.

        Name/type matching needs presentation-JSON locale names, which SQL
        ``ilike`` cannot reach without also matching excluded long-text
        ``desc`` fields (M07-D D1 F10); room-scoped custom counts stay small.
        """
        stmt = select(monster_templates).where(monster_templates.c.room_id == room_id)
        if not include_archived:
            stmt = stmt.where(monster_templates.c.archived_at.is_(None))
        stmt = stmt.order_by(monster_templates.c.name, monster_templates.c.id)

        if connection is not None:
            rows = connection.execute(stmt).mappings().all()
            return tuple(_template_from_row(row) for row in rows)
        with self.engine.connect() as conn:
            rows = conn.execute(stmt).mappings().all()
            return tuple(_template_from_row(row) for row in rows)

    def get_custom_template(
        self,
        room_id: UUID,
        template_id: UUID,
        *,
        for_update: bool = False,
        connection: Connection | None = None,
    ) -> StoredMonsterTemplate | None:
        stmt = select(monster_templates).where(
            monster_templates.c.room_id == room_id,
            monster_templates.c.id == template_id,
        )
        if for_update:
            stmt = stmt.with_for_update()

        if connection is not None:
            row = connection.execute(stmt).mappings().first()
            return _template_from_row(row) if row is not None else None
        with self.engine.connect() as conn:
            row = conn.execute(stmt).mappings().first()
            return _template_from_row(row) if row is not None else None

    def create_custom_template(
        self,
        *,
        room_id: UUID,
        name: str,
        rules: dict[str, object],
        source_key: str | None = None,
        presentation_json: dict[str, object] | None = None,
        template_id: UUID | None = None,
        connection: Connection | None = None,
    ) -> StoredMonsterTemplate:
        actual_id = template_id or uuid4()
        now = datetime.now(timezone.utc)
        presentation = dict(presentation_json or {})

        stmt = insert(monster_templates).values(
            id=actual_id,
            room_id=room_id,
            name=name,
            source_key=source_key,
            rules=rules,
            revision=1,
            archived_at=None,
            presentation_json=presentation,
            created_at=now,
            updated_at=now,
        )

        if connection is not None:
            connection.execute(stmt)
        else:
            with self.engine.begin() as conn:
                conn.execute(stmt)

        return StoredMonsterTemplate(
            id=actual_id,
            room_id=room_id,
            name=name,
            source_key=source_key,
            rules=rules,
            revision=1,
            archived_at=None,
            presentation_json=presentation,
            created_at=now,
            updated_at=now,
        )

    def update_custom_template(
        self,
        *,
        room_id: UUID,
        template_id: UUID,
        expected_revision: int,
        name: str | None = None,
        rules: dict[str, object] | None = None,
        presentation_json: dict[str, object] | None = None,
        connection: Connection | None = None,
    ) -> StoredMonsterTemplate:
        def _update(conn: Connection) -> StoredMonsterTemplate:
            stmt = (
                select(monster_templates)
                .where(
                    monster_templates.c.room_id == room_id,
                    monster_templates.c.id == template_id,
                )
                .with_for_update()
            )
            row = conn.execute(stmt).mappings().first()
            if row is None:
                raise MonsterTemplateNotFoundError(
                    f"monster template '{template_id}' not found in room '{room_id}'"
                )
            if row["revision"] != expected_revision:
                raise MonsterTemplateRevisionConflictError(
                    f"monster template revision conflict: expected {expected_revision}, got {row['revision']}"
                )

            values: dict[str, object] = {
                "revision": expected_revision + 1,
                "updated_at": datetime.now(timezone.utc),
            }
            if name is not None:
                values["name"] = name
            if rules is not None:
                values["rules"] = rules
            if presentation_json is not None:
                values["presentation_json"] = presentation_json

            conn.execute(
                update(monster_templates)
                .where(
                    monster_templates.c.room_id == room_id,
                    monster_templates.c.id == template_id,
                )
                .values(**values)
            )

            updated_row = conn.execute(
                select(monster_templates).where(
                    monster_templates.c.room_id == room_id,
                    monster_templates.c.id == template_id,
                )
            ).mappings().one()
            return _template_from_row(updated_row)

        if connection is not None:
            return _update(connection)
        with self.engine.begin() as conn:
            return _update(conn)

    def archive_custom_template(
        self,
        *,
        room_id: UUID,
        template_id: UUID,
        expected_revision: int,
        connection: Connection | None = None,
    ) -> StoredMonsterTemplate:
        def _archive(conn: Connection) -> StoredMonsterTemplate:
            stmt = (
                select(monster_templates)
                .where(
                    monster_templates.c.room_id == room_id,
                    monster_templates.c.id == template_id,
                )
                .with_for_update()
            )
            row = conn.execute(stmt).mappings().first()
            if row is None:
                raise MonsterTemplateNotFoundError(
                    f"monster template '{template_id}' not found in room '{room_id}'"
                )
            if row["revision"] != expected_revision:
                raise MonsterTemplateRevisionConflictError(
                    f"monster template revision conflict: expected {expected_revision}, got {row['revision']}"
                )

            now = datetime.now(timezone.utc)
            conn.execute(
                update(monster_templates)
                .where(
                    monster_templates.c.room_id == room_id,
                    monster_templates.c.id == template_id,
                )
                .values(
                    archived_at=now,
                    revision=expected_revision + 1,
                    updated_at=now,
                )
            )

            archived_row = conn.execute(
                select(monster_templates).where(
                    monster_templates.c.room_id == room_id,
                    monster_templates.c.id == template_id,
                )
            ).mappings().one()
            return _template_from_row(archived_row)

        if connection is not None:
            return _archive(connection)
        with self.engine.begin() as conn:
            return _archive(conn)

    def delete_custom_template(
        self,
        *,
        room_id: UUID,
        template_id: UUID,
        expected_revision: int,
        connection: Connection | None = None,
    ) -> None:
        def _delete(conn: Connection) -> None:
            stmt = (
                select(monster_templates)
                .where(
                    monster_templates.c.room_id == room_id,
                    monster_templates.c.id == template_id,
                )
                .with_for_update()
            )
            row = conn.execute(stmt).mappings().first()
            if row is None:
                raise MonsterTemplateNotFoundError(
                    f"monster template '{template_id}' not found in room '{room_id}'"
                )
            if row["revision"] != expected_revision:
                raise MonsterTemplateRevisionConflictError(
                    f"monster template revision conflict: expected {expected_revision}, got {row['revision']}"
                )
            conn.execute(
                delete(monster_templates).where(
                    monster_templates.c.room_id == room_id,
                    monster_templates.c.id == template_id,
                )
            )

        if connection is not None:
            _delete(connection)
        else:
            with self.engine.begin() as conn:
                _delete(conn)
