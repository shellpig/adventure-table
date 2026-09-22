from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from pydantic import ValidationError
import pytest

from app.domain.adventures.payloads import (
    DmNotePayload,
    ItemPayload,
    LorePayload,
    MapPayload,
    MonsterRefPayload,
    NpcPayload,
    OtherPayload,
    QuestPayload,
    ScenePayload,
    SectionPayload,
    SecretPayload,
    SuggestedCheckPayload,
)
from app.domain.adventure_imports.schemas import (
    DraftEntry,
    DraftQuestion,
    DraftSourceRef,
    DraftWarning,
    ImportDraft,
    adventure_import_draft_from_stored,
    adventure_import_from_stored,
    adventure_import_source_from_stored,
    validate_draft_warnings,
)
from app.persistence.adventure_imports.repository import (
    StoredAdventureImport,
    StoredAdventureImportDraft,
    StoredAdventureImportSource,
)


@pytest.mark.parametrize(
    ("entry_kind", "payload_input"),
    [
        ("section", SectionPayload()),
        ("scene", ScenePayload(read_aloud="Look here.")),
        ("npc", NpcPayload(role="Merchant")),
        ("item", ItemPayload(value_gp=50)),
        ("monster_ref", MonsterRefPayload(monster_template_ref="goblin", count=2)),
        ("quest", QuestPayload(objective="Find the relic")),
        ("secret", SecretPayload(reveal_condition="DC 15 Investigation")),
        ("dm_note", DmNotePayload()),
        ("suggested_check", SuggestedCheckPayload(ability="wis", dc=12)),
        ("map", MapPayload(caption="Ground Floor")),
        ("lore", LorePayload(topic="The Old Kingdom")),
        ("other", OtherPayload(data={"key": "val"})),
        # Also verify dict input parsed via reused payload validator
        ("scene", {"read_aloud": "Parsed from dict"}),
        ("npc", {"role": "Guard", "disposition": "hostile"}),
    ],
)
def test_import_draft_accepts_valid_entry_per_kind(
    entry_kind: str,
    payload_input: object,
) -> None:
    source_ref = DraftSourceRef(source_id=uuid4(), locator="p. 12")
    entry = DraftEntry(
        entry_id="ent-1",
        entry_kind=entry_kind,  # type: ignore[arg-type]
        payload=payload_input,  # type: ignore[arg-type]
        provenance="source_document",
        source_ref=source_ref,
    )
    draft = ImportDraft(schema_version=1, entries=[entry], questions=[])
    assert len(draft.entries) == 1
    assert draft.entries[0].entry_kind == entry_kind
    assert draft.entries[0].payload.kind == entry_kind


@pytest.mark.parametrize(
    ("entry_kind", "mismatched_payload"),
    [
        ("scene", NpcPayload(role="Bartender")),
        ("npc", ScenePayload(read_aloud="A noisy room")),
        ("scene", {"kind": "npc", "role": "Guard"}),
        ("quest", {"kind": "item", "value_gp": 100}),
    ],
)
def test_draft_entry_rejects_payload_kind_mismatch(
    entry_kind: str,
    mismatched_payload: object,
) -> None:
    with pytest.raises(ValidationError):
        DraftEntry(
            entry_id="ent-1",
            entry_kind=entry_kind,  # type: ignore[arg-type]
            payload=mismatched_payload,  # type: ignore[arg-type]
        )


def test_import_draft_rejects_duplicate_ids() -> None:
    # Duplicate entry_id
    with pytest.raises(ValidationError, match="Duplicate entry_id"):
        ImportDraft(
            schema_version=1,
            entries=[
                DraftEntry(
                    entry_id="ent-dup",
                    entry_kind="section",
                    payload=SectionPayload(),
                ),
                DraftEntry(
                    entry_id="ent-dup",
                    entry_kind="scene",
                    payload=ScenePayload(),
                ),
            ],
            questions=[],
        )

    # Duplicate question_id
    with pytest.raises(ValidationError, match="Duplicate question_id"):
        ImportDraft(
            schema_version=1,
            entries=[],
            questions=[
                DraftQuestion(question_id="q-dup", message="First?"),
                DraftQuestion(question_id="q-dup", message="Second?"),
            ],
        )

    # Duplicate warning_id
    with pytest.raises(ValueError, match="Duplicate warning_id"):
        validate_draft_warnings(
            [
                DraftWarning(
                    warning_id="w-dup",
                    level="info",
                    code="CODE_1",
                    message="Msg 1",
                ),
                DraftWarning(
                    warning_id="w-dup",
                    level="warning",
                    code="CODE_2",
                    message="Msg 2",
                ),
            ]
        )


def test_import_draft_rejects_dangling_and_self_parent_entry_id() -> None:
    # Dangling parent
    with pytest.raises(ValidationError, match="references non-existent parent_entry_id"):
        ImportDraft(
            schema_version=1,
            entries=[
                DraftEntry(
                    entry_id="ent-1",
                    entry_kind="scene",
                    payload=ScenePayload(),
                    parent_entry_id="non-existent",
                )
            ],
            questions=[],
        )

    # Self-referential parent
    with pytest.raises(ValidationError, match="cannot reference itself as parent_entry_id"):
        ImportDraft(
            schema_version=1,
            entries=[
                DraftEntry(
                    entry_id="ent-1",
                    entry_kind="scene",
                    payload=ScenePayload(),
                    parent_entry_id="ent-1",
                )
            ],
            questions=[],
        )


def test_draft_entry_rejects_unknown_provenance() -> None:
    with pytest.raises(ValidationError):
        DraftEntry(
            entry_id="ent-1",
            entry_kind="scene",
            payload=ScenePayload(),
            provenance="hallucinated",  # type: ignore[arg-type]
        )


def test_import_draft_rejects_schema_version_not_one() -> None:
    with pytest.raises(ValidationError):
        ImportDraft.model_validate(
            {"schema_version": 2, "entries": [], "questions": []}
        )


def test_view_models_and_stored_conversions() -> None:
    now = datetime.now(timezone.utc)
    import_id = uuid4()
    room_id = uuid4()
    adv_id = uuid4()
    source_id = uuid4()

    # 1. AdventureImport
    stored_import = StoredAdventureImport(
        id=import_id,
        room_id=room_id,
        name="Import Test",
        status="source",
        target_adventure_id=adv_id,
        revision=0,
        created_at=now,
        updated_at=now,
    )
    domain_import = adventure_import_from_stored(stored_import)
    assert domain_import.id == import_id
    assert domain_import.status == "source"

    # 2. AdventureImportSource
    stored_source = StoredAdventureImportSource(
        id=source_id,
        import_id=import_id,
        asset_id=None,
        source_kind="markdown",
        source_url="https://example.com/doc",
        metadata_json={"author": "DM"},
        sha256="a" * 64,
        created_at=now,
        normalized_text=None,
        text_length=120,
    )
    domain_source = adventure_import_source_from_stored(stored_source)
    assert domain_source.id == source_id
    assert domain_source.text_length == 120
    assert not hasattr(domain_source, "normalized_text")

    # 3. AdventureImportDraft
    draft_dict = {
        "schema_version": 1,
        "entries": [
            {
                "entry_id": "e-1",
                "entry_kind": "scene",
                "payload": {"kind": "scene", "read_aloud": "A cold wind blows."},
                "parent_entry_id": None,
                "provenance": "source_document",
                "source_ref": None,
                "note": None,
            }
        ],
        "questions": [],
    }
    warnings_list = [
        {
            "warning_id": "w-1",
            "level": "warning",
            "code": "LOW_CONFIDENCE",
            "message": "Check needed",
            "entry_id": "e-1",
            "source_id": None,
        }
    ]
    stored_draft = StoredAdventureImportDraft(
        import_id=import_id,
        draft_json=draft_dict,
        warnings_json=warnings_list,
        revision=1,
        updated_at=now,
    )
    domain_draft = adventure_import_draft_from_stored(stored_draft)
    assert domain_draft.import_id == import_id
    assert domain_draft.revision == 1
    assert len(domain_draft.draft.entries) == 1
    assert len(domain_draft.warnings) == 1
    assert domain_draft.warnings[0].warning_id == "w-1"
