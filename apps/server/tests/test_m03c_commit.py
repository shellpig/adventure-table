from __future__ import annotations

import copy
from uuid import UUID, uuid4

import pytest
from sqlalchemy import event, insert, select
from sqlalchemy.exc import IntegrityError

from app.interop.json_schema import CharacterExport
from app.persistence.builder_drafts import character_build_drafts
from app.persistence.character_imports import character_import_records
from app.persistence.characters import characters, character_states, character_versions
from m03c_support import document, seeded_import


def _two_version_document(*, current_version_no: int = 2) -> dict:
    payload = document()
    first = copy.deepcopy(payload["payload"]["versions"][0])
    first["version_no"] = 1
    first["parent_version_no"] = None
    first["superseded_by_version_no"] = 2
    second = copy.deepcopy(first)
    second["version_no"] = 2
    second["version_kind"] = "build_edit"
    second["parent_version_no"] = 1
    second["superseded_by_version_no"] = None
    payload["payload"]["versions"] = [first, second]
    payload["payload"]["current_version_no"] = current_version_no
    return payload


def test_commit_import_as_character_preserves_chain_provenance_and_state() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = _two_version_document(current_version_no=1)
    source_character_id = UUID(payload["envelope"]["source_character_id"])

    statements: list[str] = []

    def capture(_conn, _cursor, statement, _parameters, _context, _executemany):
        normalized = " ".join(statement.lower().split())
        if "character_versions" in normalized:
            statements.append(normalized)

    event.listen(engine, "before_cursor_execute", capture)
    try:
        result = service.commit(CharacterExport.model_validate(payload))
    finally:
        event.remove(engine, "before_cursor_execute", capture)

    assert result.committed is True
    assert result.character_id is not None
    assert result.character_id != source_character_id
    assert result.draft_id is None

    first_update = next(i for i, sql in enumerate(statements) if sql.startswith("update"))
    assert all(sql.startswith("insert") for sql in statements[:first_update])
    assert any(sql.startswith("update") for sql in statements[first_update:])

    with engine.connect() as connection:
        version_rows = connection.execute(
            select(character_versions)
            .where(character_versions.c.character_id == result.character_id)
            .order_by(character_versions.c.version_no)
        ).mappings().all()
        assert [row["version_no"] for row in version_rows] == [1, 2]
        assert version_rows[0]["superseded_by_version_id"] == version_rows[1]["id"]
        assert version_rows[1]["parent_version_id"] == version_rows[0]["id"]
        assert version_rows[0]["builder_provenance"] == payload["payload"]["versions"][0]["builder_provenance"]
        assert version_rows[1]["builder_provenance"] == payload["payload"]["versions"][1]["builder_provenance"]

        character = connection.execute(
            select(characters).where(characters.c.id == result.character_id)
        ).mappings().one()
        assert character["current_version_id"] == version_rows[0]["id"]

        state = connection.execute(
            select(character_states).where(character_states.c.character_id == result.character_id)
        ).mappings().one()
        assert state["state_payload"] == payload["payload"]["current_state"]["state_payload"]

        record = connection.execute(
            select(character_import_records).where(
                character_import_records.c.character_id == result.character_id
            )
        ).mappings().one()
        assert record["landing_mode"] == "character"
        assert record["draft_id"] is None
    engine.dispose()


@pytest.mark.parametrize(
    ("fixture_name", "disabled_pack", "expected_mode"),
    [
        ("fixture_xge_dependent.json", "xge", "draft"),
        ("fixture_state_only_missing_inventory.json", None, "draft_with_history_loss"),
    ],
)
def test_commit_import_as_fresh_create_draft(
    fixture_name: str,
    disabled_pack: str | None,
    expected_mode: str,
) -> None:
    client, engine, _ = seeded_import(disabled_pack=disabled_pack)
    service = client.app.state.character_import_service
    payload = document(fixture_name)
    result = service.commit(CharacterExport.model_validate(payload))

    assert result.character_id is None
    assert result.draft_id is not None
    assert result.landing_mode == expected_mode

    with engine.connect() as connection:
        draft = connection.execute(
            select(character_build_drafts).where(character_build_drafts.c.id == result.draft_id)
        ).mappings().one()
        assert draft["mode"] == "create"
        assert draft["character_id"] is None
        assert draft["base_version_id"] is None
        assert draft["draft_payload"]["initial_state_seed"] == {}

        record = connection.execute(
            select(character_import_records).where(
                character_import_records.c.draft_id == result.draft_id
            )
        ).mappings().one()
        assert record["landing_mode"] == expected_mode
        assert record["character_id"] is None
        assert connection.execute(select(character_states)).all() == []

        if expected_mode == "draft":
            assert draft["draft_payload"]["level_choices"][-1]["subclass_ref"] is None
    engine.dispose()


def test_character_import_record_constraint_allows_no_target_but_not_two_targets() -> None:
    client, engine, _ = seeded_import()
    both_target_id = uuid4()
    base = {
        "id": uuid4(),
        "source_character_id": uuid4(),
        "source_export_id": uuid4(),
        "landing_mode": "character",
    }
    with engine.begin() as connection:
        connection.execute(
            insert(character_import_records).values(
                **base,
                character_id=None,
                draft_id=None,
            )
        )

    with pytest.raises(IntegrityError):
        with engine.begin() as connection:
            connection.execute(
                insert(character_import_records).values(
                    id=uuid4(),
                    character_id=both_target_id,
                    draft_id=both_target_id,
                    source_character_id=uuid4(),
                    source_export_id=uuid4(),
                    landing_mode="draft",
                )
            )
    engine.dispose()
