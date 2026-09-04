from __future__ import annotations

from app.interop.json_schema import CharacterExport
from sqlalchemy import func, select

from app.persistence.character_imports import character_import_records
from m03c_support import document, seeded_import


def test_duplicate_hint_is_none_before_first_import() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = CharacterExport.model_validate(document())
    assert service.preview(payload).duplicate_hint is None
    engine.dispose()


def test_duplicate_hint_reports_count_and_latest_after_import() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = CharacterExport.model_validate(document())
    service.commit(payload)
    hint = service.preview(payload).duplicate_hint
    assert hint is not None
    assert hint.count == 1
    assert hint.latest_imported_at is not None
    engine.dispose()


def test_duplicate_hint_does_not_block_another_commit() -> None:
    client, engine, _ = seeded_import()
    service = client.app.state.character_import_service
    payload = CharacterExport.model_validate(document())
    first = service.commit(payload)
    second = service.commit(payload)
    assert first.character_id != second.character_id
    with engine.connect() as connection:
        assert connection.scalar(select(func.count(character_import_records.c.id))) == 2
    engine.dispose()
