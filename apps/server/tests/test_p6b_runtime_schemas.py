from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from pydantic import ValidationError
import pytest

from app.domain.campaign_runtime import (
    KNOWN_ITEM_HOLDER_KINDS,
    KNOWN_RUNTIME_ENTRY_KINDS,
    KNOWN_RUNTIME_VISIBILITIES,
    RuntimeEntryKind,
    RuntimeEntryPayloadError,
    RuntimeEntryValidationError,
    RuntimeEntryVisibilityError,
    RuntimeFactPayload,
    RuntimeHazardPayload,
    RuntimeItemHolderRef,
    RuntimeItemPayload,
    RuntimeNpcPayload,
    RuntimeOtherPayload,
    RuntimeQuestPayload,
    RuntimeScenePayload,
    RuntimeSecretPayload,
    RuntimeVisibility,
    RuntimeWorldEntry,
    RuntimeWorldEntryCreate,
    RuntimeWorldEntryDmView,
    RuntimeWorldEntryPatch,
    RuntimeWorldEntryPlayerView,
    dump_runtime_payload,
    parse_runtime_payload,
    project_runtime_entry,
    validate_entry_quick_add_minima,
    validate_runtime_visibility_recipients,
)


def test_parse_and_dump_every_known_kind() -> None:
    # 1. scene
    scene = parse_runtime_payload("scene", {})
    assert isinstance(scene, RuntimeScenePayload)
    assert scene.kind == "scene"
    assert dump_runtime_payload(scene) == {"kind": "scene"}

    # 2. npc
    npc_min = parse_runtime_payload("npc", {})
    assert isinstance(npc_min, RuntimeNpcPayload)
    assert npc_min.monster_instance_id is None
    assert npc_min.monster_template_ref is None

    inst_id = uuid4()
    npc_full = parse_runtime_payload(
        "npc",
        {
            "monster_instance_id": str(inst_id),
            "monster_template_ref": "goblin-boss",
        },
    )
    assert isinstance(npc_full, RuntimeNpcPayload)
    assert npc_full.monster_instance_id == inst_id
    assert npc_full.monster_template_ref == "goblin-boss"
    dumped_npc = dump_runtime_payload(npc_full)
    assert dumped_npc["monster_instance_id"] == str(inst_id)
    assert dumped_npc["monster_template_ref"] == "goblin-boss"

    # 3. item
    item_min = parse_runtime_payload("item", {})
    assert isinstance(item_min, RuntimeItemPayload)
    assert item_min.holder_ref is None
    assert dump_runtime_payload(item_min) == {"kind": "item", "holder_ref": None}

    holder_target = uuid4()
    item_holder = parse_runtime_payload(
        "item",
        {
            "holder_ref": {
                "kind": "npc",
                "target_id": str(holder_target),
            }
        },
    )
    assert isinstance(item_holder, RuntimeItemPayload)
    assert item_holder.holder_ref is not None
    assert item_holder.holder_ref.kind == "npc"
    assert item_holder.holder_ref.target_id == holder_target

    # 4. quest
    quest = parse_runtime_payload("quest", {})
    assert isinstance(quest, RuntimeQuestPayload)
    assert quest.kind == "quest"
    assert dump_runtime_payload(quest) == {"kind": "quest"}

    # 5. fact
    fact = parse_runtime_payload("fact", {})
    assert isinstance(fact, RuntimeFactPayload)
    assert fact.kind == "fact"
    assert dump_runtime_payload(fact) == {"kind": "fact"}

    # 6. secret
    secret = parse_runtime_payload("secret", {})
    assert isinstance(secret, RuntimeSecretPayload)
    assert secret.kind == "secret"
    assert dump_runtime_payload(secret) == {"kind": "secret"}

    # 7. hazard
    hazard = parse_runtime_payload("hazard", {})
    assert isinstance(hazard, RuntimeHazardPayload)
    assert hazard.kind == "hazard"
    assert dump_runtime_payload(hazard) == {"kind": "hazard"}

    # 8. other
    other_empty = parse_runtime_payload("other", {})
    assert isinstance(other_empty, RuntimeOtherPayload)
    assert other_empty.kind == "other"
    assert other_empty.data == {}

    other_data = parse_runtime_payload(
        "other",
        {
            "data": {
                "str_key": "text",
                "int_key": 42,
                "float_key": 3.14,
                "bool_key": True,
            }
        },
    )
    assert isinstance(other_data, RuntimeOtherPayload)
    assert other_data.data["str_key"] == "text"
    assert other_data.data["int_key"] == 42
    assert other_data.data["float_key"] == 3.14
    assert other_data.data["bool_key"] is True


def test_parse_rejections_non_dict_kind_mismatch_unknown_and_extra_keys() -> None:
    # Non-dict
    with pytest.raises(RuntimeEntryPayloadError, match="must be a dictionary"):
        parse_runtime_payload("scene", "not-a-dict")  # type: ignore[arg-type]
    with pytest.raises(RuntimeEntryPayloadError, match="must be a dictionary"):
        parse_runtime_payload("scene", [1, 2, 3])  # type: ignore[arg-type]
    with pytest.raises(RuntimeEntryPayloadError, match="must be a dictionary"):
        parse_runtime_payload("scene", None)  # type: ignore[arg-type]

    # Kind mismatch
    with pytest.raises(RuntimeEntryPayloadError, match="does not match entry kind"):
        parse_runtime_payload("scene", {"kind": "npc"})

    # Unknown entry kind
    with pytest.raises(RuntimeEntryPayloadError, match="Unknown runtime entry kind"):
        parse_runtime_payload("unknown_kind", {})

    # Extra keys on kind-only models
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("scene", {"extra": "field"})
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("quest", {"status": "in_progress"})
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("fact", {"truth_value": True})
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("secret", {"dc": 15})
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("hazard", {"damage": "2d6"})

    # Extra keys on npc, item, other
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("npc", {"unknown_field": "test"})
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("item", {"extra": 123})
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("other", {"extra": "not_in_data"})


def test_npc_refs_validation() -> None:
    # Blank monster_template_ref rejected
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("npc", {"monster_template_ref": ""})
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("npc", {"monster_template_ref": "   "})

    # Valid template ref normalized
    npc = parse_runtime_payload("npc", {"monster_template_ref": "  goblin  "})
    assert isinstance(npc, RuntimeNpcPayload)
    assert npc.monster_template_ref == "goblin"

    # Invalid monster_instance_id rejected
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("npc", {"monster_instance_id": "not-a-uuid"})


def test_item_holder_kinds_and_target_combinations() -> None:
    target = uuid4()

    # scene, npc, character require target_id
    for kind in ("scene", "npc", "character"):
        valid = parse_runtime_payload(
            "item",
            {"holder_ref": {"kind": kind, "target_id": str(target)}},
        )
        assert isinstance(valid, RuntimeItemPayload)
        assert valid.holder_ref is not None
        assert valid.holder_ref.kind == kind
        assert valid.holder_ref.target_id == target

        # Missing target_id
        with pytest.raises(RuntimeEntryPayloadError, match="target_id is required"):
            parse_runtime_payload("item", {"holder_ref": {"kind": kind}})
        with pytest.raises(RuntimeEntryPayloadError, match="target_id is required"):
            parse_runtime_payload("item", {"holder_ref": {"kind": kind, "target_id": None}})

    # party, unknown must not have target_id
    for kind in ("party", "unknown"):
        valid = parse_runtime_payload(item_kind := "item", {"holder_ref": {"kind": kind}})
        assert isinstance(valid, RuntimeItemPayload)
        assert valid.holder_ref is not None
        assert valid.holder_ref.kind == kind
        assert valid.holder_ref.target_id is None

        # Setting target_id is an error
        with pytest.raises(RuntimeEntryPayloadError, match="target_id must not be set"):
            parse_runtime_payload(
                "item",
                {"holder_ref": {"kind": kind, "target_id": str(target)}},
            )

    # Invalid holder kind
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("item", {"holder_ref": {"kind": "room", "target_id": str(target)}})

    # Non-dict holder_ref
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("item", {"holder_ref": "backpack"})


def test_other_payload_data_scalars() -> None:
    # Nested dict rejected
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("other", {"data": {"nested": {"a": 1}}})

    # List rejected
    with pytest.raises(RuntimeEntryPayloadError):
        parse_runtime_payload("other", {"data": {"items": [1, 2, 3]}})


def test_quick_add_minima() -> None:
    # NPC requires nonblank title
    with pytest.raises(RuntimeEntryValidationError, match="NPC requires a nonblank title"):
        validate_entry_quick_add_minima("npc", None, None)
    with pytest.raises(RuntimeEntryValidationError, match="NPC requires a nonblank title"):
        validate_entry_quick_add_minima("npc", "   ", "some body")
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(kind="npc", title=None)
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(kind="npc", title="   ")

    # Valid NPC
    create_npc = RuntimeWorldEntryCreate(kind="npc", title="Bartender Bob")
    assert create_npc.title == "Bartender Bob"

    # Fact requires nonblank body
    with pytest.raises(RuntimeEntryValidationError, match="Fact requires a nonblank body"):
        validate_entry_quick_add_minima("fact", "Title", None)
    with pytest.raises(RuntimeEntryValidationError, match="Fact requires a nonblank body"):
        validate_entry_quick_add_minima("fact", "Title", "   ")
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(kind="fact", title="Some Title", body=None)

    # Valid Fact
    create_fact = RuntimeWorldEntryCreate(kind="fact", body="The local bridge collapsed.")
    assert create_fact.body == "The local bridge collapsed."

    # Scene requires at least nonblank title or body
    with pytest.raises(
        RuntimeEntryValidationError,
        match="Scene requires at least a nonblank title or body",
    ):
        validate_entry_quick_add_minima("scene", None, None)
    with pytest.raises(
        RuntimeEntryValidationError,
        match="Scene requires at least a nonblank title or body",
    ):
        validate_entry_quick_add_minima("scene", "   ", "   ")
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(kind="scene", title=None, body=None)

    # Valid Scenes: title only, body only, both
    scene_title = RuntimeWorldEntryCreate(kind="scene", title="Tavern")
    assert scene_title.title == "Tavern"
    scene_body = RuntimeWorldEntryCreate(kind="scene", body="A dimly lit cellar.")
    assert scene_body.body == "A dimly lit cellar."
    scene_both = RuntimeWorldEntryCreate(kind="scene", title="Tavern", body="A bustling tavern.")
    assert scene_both.title == "Tavern"
    assert scene_both.body == "A bustling tavern."

    # Other kinds have no title/body minima
    for kind in ("item", "quest", "secret", "hazard", "other"):
        validate_entry_quick_add_minima(kind, None, None)  # type: ignore[arg-type]
        created = RuntimeWorldEntryCreate(kind=kind)  # type: ignore[arg-type]
        assert created.kind == kind
        assert created.title is None
        assert created.body is None


def test_runtime_world_entry_create_validates_raw_state() -> None:
    # Valid state normalized
    npc_create = RuntimeWorldEntryCreate(
        kind="npc",
        title="Goblin Guard",
        state={"monster_template_ref": "  goblin  "},
    )
    assert npc_create.state["monster_template_ref"] == "goblin"
    assert npc_create.state["kind"] == "npc"

    scene_create = RuntimeWorldEntryCreate(kind="scene", title="Cave")
    assert scene_create.state == {"kind": "scene"}

    # Invalid state: kind mismatch
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(kind="scene", title="Cave", state={"kind": "npc"})

    # Invalid state: extra keys
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(kind="scene", title="Cave", state={"extra_field": 123})

    # Invalid state: blank NPC template ref
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(
            kind="npc",
            title="Goblin",
            state={"monster_template_ref": "   "},
        )

    # Invalid state: item holder missing target_id
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(
            kind="item",
            title="Key",
            state={"holder_ref": {"kind": "scene"}},
        )

    # Invalid state: item holder party with target_id
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(
            kind="item",
            title="Gold",
            state={"holder_ref": {"kind": "party", "target_id": str(uuid4())}},
        )

    # Invalid state: other with non-scalar data
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(
            kind="other",
            state={"data": {"nested": {"a": 1}}},
        )


def test_runtime_world_entry_single_source_of_truth() -> None:
    now = datetime.now(timezone.utc)
    entry_id = uuid4()
    campaign_id = uuid4()

    # 1. Construct with state
    entry_from_state = RuntimeWorldEntry(
        id=entry_id,
        campaign_id=campaign_id,
        kind="scene",
        title="Tavern",
        state=RuntimeScenePayload(kind="scene"),
        created_by_actor_kind="dm",
        created_at=now,
        updated_at=now,
    )
    assert isinstance(entry_from_state.state, RuntimeScenePayload)
    assert entry_from_state.state_json == {"kind": "scene"}

    # 2. Construct with state_json
    entry_from_json = RuntimeWorldEntry(
        id=entry_id,
        campaign_id=campaign_id,
        kind="scene",
        title="Tavern",
        state_json={"kind": "scene"},
        created_by_actor_kind="dm",
        created_at=now,
        updated_at=now,
    )
    assert isinstance(entry_from_json.state, RuntimeScenePayload)
    assert entry_from_json.state_json == {"kind": "scene"}

    # 3. Construct with both state and state_json is REJECTED
    with pytest.raises(ValidationError, match="Cannot specify both 'state' and 'state_json'"):
        RuntimeWorldEntry(
            id=entry_id,
            campaign_id=campaign_id,
            kind="scene",
            title="Tavern",
            state=RuntimeScenePayload(kind="scene"),
            state_json={"kind": "scene"},
            created_by_actor_kind="dm",
            created_at=now,
            updated_at=now,
        )

    with pytest.raises(ValidationError, match="state_json must be a dictionary"):
        RuntimeWorldEntry(
            id=uuid4(),
            campaign_id=uuid4(),
            kind="scene",
            state_json=[],
            visibility="public",
            revision=1,
            created_by_actor_kind="human",
            created_at=now,
            updated_at=now,
        )

    # 4. Model dump has single state representation (no state_json field)
    dumped = entry_from_state.model_dump()
    assert "state" in dumped
    assert "state_json" not in dumped


def test_runtime_world_entry_patch_rejects_kind_as_extra_field() -> None:
    with pytest.raises(ValidationError):
        RuntimeWorldEntryPatch(
            expected_revision=1,
            kind="npc",  # type: ignore[call-arg]
            title="New Title",
        )


def test_patch_omitted_vs_null_empty_patch_and_revision() -> None:
    # Missing expected_revision
    with pytest.raises(ValidationError):
        RuntimeWorldEntryPatch(title="New Title")  # type: ignore[call-arg]

    # Non-positive expected_revision
    with pytest.raises(ValidationError):
        RuntimeWorldEntryPatch(expected_revision=0, title="New Title")
    with pytest.raises(ValidationError):
        RuntimeWorldEntryPatch(expected_revision=-1, title="New Title")

    # Empty patch (only expected_revision)
    with pytest.raises(ValidationError, match="at least one patch field"):
        RuntimeWorldEntryPatch(expected_revision=1)

    # Omitted vs explicit null
    patch_omitted = RuntimeWorldEntryPatch(expected_revision=1, body="Updated body")
    assert "title" not in patch_omitted.model_fields_set
    assert "body" in patch_omitted.model_fields_set
    assert patch_omitted.body == "Updated body"

    patch_explicit_null = RuntimeWorldEntryPatch(expected_revision=1, title=None)
    assert "title" in patch_explicit_null.model_fields_set
    assert patch_explicit_null.title is None

    # Title max 200
    valid_title_patch = RuntimeWorldEntryPatch(expected_revision=1, title="a" * 200)
    assert valid_title_patch.title == "a" * 200
    with pytest.raises(ValidationError):
        RuntimeWorldEntryPatch(expected_revision=1, title="a" * 201)

    # Non-nullable fields on patch
    with pytest.raises(ValidationError, match="visibility cannot be null"):
        RuntimeWorldEntryPatch(expected_revision=1, visibility=None)
    with pytest.raises(ValidationError, match="state cannot be null"):
        RuntimeWorldEntryPatch(expected_revision=1, state=None)
    with pytest.raises(ValidationError, match="character_recipient_ids cannot be null"):
        RuntimeWorldEntryPatch(expected_revision=1, character_recipient_ids=None)
    with pytest.raises(ValidationError, match="needs_review cannot be null"):
        RuntimeWorldEntryPatch(expected_revision=1, needs_review=None)


def test_visibility_recipient_invariant() -> None:
    char_id1 = uuid4()
    char_id2 = uuid4()

    # Reusable helper direct validation
    validate_runtime_visibility_recipients("character", (char_id1,))
    validate_runtime_visibility_recipients("character", (char_id1, char_id2))
    validate_runtime_visibility_recipients("public", ())
    validate_runtime_visibility_recipients("dm_only", ())

    with pytest.raises(
        RuntimeEntryVisibilityError,
        match="Character visibility requires at least one character recipient",
    ):
        validate_runtime_visibility_recipients("character", ())

    with pytest.raises(
        RuntimeEntryVisibilityError,
        match="public visibility must not have character recipients",
    ):
        validate_runtime_visibility_recipients("public", (char_id1,))

    with pytest.raises(
        RuntimeEntryVisibilityError,
        match="dm_only visibility must not have character recipients",
    ):
        validate_runtime_visibility_recipients("dm_only", (char_id1,))

    with pytest.raises(RuntimeEntryVisibilityError, match="recipients must be unique"):
        validate_runtime_visibility_recipients("character", (char_id1, char_id1))

    with pytest.raises(RuntimeEntryVisibilityError, match="Unknown visibility"):
        validate_runtime_visibility_recipients("invalid_vis", ())  # type: ignore[arg-type]

    # Enforcement in RuntimeWorldEntryCreate
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(
            kind="scene",
            title="Secret Hideout",
            visibility="character",
            character_recipient_ids=(),
        )
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(
            kind="scene",
            title="Town Square",
            visibility="public",
            character_recipient_ids=(char_id1,),
        )
    with pytest.raises(ValidationError):
        RuntimeWorldEntryCreate(
            kind="secret",
            visibility="dm_only",
            character_recipient_ids=(char_id1,),
        )

    # Enforcement in canonical RuntimeWorldEntry
    now = datetime.now(timezone.utc)
    with pytest.raises(ValidationError):
        RuntimeWorldEntry(
            id=uuid4(),
            campaign_id=uuid4(),
            kind="scene",
            title="Town Square",
            state_json={},
            visibility="public",
            character_recipient_ids=(char_id1,),
            revision=1,
            created_by_actor_kind="user",
            created_at=now,
            updated_at=now,
        )


def test_projection_call_safety_requires_explicit_keyword_audience() -> None:
    now = datetime.now(timezone.utc)
    entry = RuntimeWorldEntry(
        id=uuid4(),
        campaign_id=uuid4(),
        kind="scene",
        title="Public Square",
        state_json={},
        created_by_actor_kind="dm",
        created_at=now,
        updated_at=now,
    )

    # Missing audience parameters
    with pytest.raises(TypeError):
        project_runtime_entry(entry)  # type: ignore[call-arg]

    # Positional audience parameters rejected
    with pytest.raises(TypeError):
        project_runtime_entry(entry, (), True)  # type: ignore[call-arg]

    # Missing is_dm
    with pytest.raises(TypeError):
        project_runtime_entry(entry, controlled_character_ids=())  # type: ignore[call-arg]

    # Missing controlled_character_ids
    with pytest.raises(TypeError):
        project_runtime_entry(entry, is_dm=True)  # type: ignore[call-arg]


def test_projection_matrix_and_player_secrecy() -> None:
    now = datetime.now(timezone.utc)
    campaign_id = uuid4()
    char_a = uuid4()
    char_b = uuid4()
    source_entry_id = uuid4()

    public_entry = RuntimeWorldEntry(
        id=uuid4(),
        campaign_id=campaign_id,
        kind="scene",
        title="Public Tavern",
        body="A bustling place.",
        state_json={},
        dm_notes="Tavern keeper is a retired spy.",
        visibility="public",
        needs_review=True,
        source_adventure_entry_id=source_entry_id,
        provenance_json={"origin": "adventure_override"},
        character_recipient_ids=(),
        revision=3,
        created_by_actor_kind="dm",
        created_by_actor_id=uuid4(),
        created_at=now,
        updated_at=now,
    )

    character_entry = RuntimeWorldEntry(
        id=uuid4(),
        campaign_id=campaign_id,
        kind="fact",
        body="Char A knows the hidden password.",
        state_json={},
        dm_notes="Only Char A was told this in secret.",
        visibility="character",
        needs_review=False,
        character_recipient_ids=(char_a,),
        revision=1,
        created_by_actor_kind="dm",
        created_at=now,
        updated_at=now,
    )

    dm_only_entry = RuntimeWorldEntry(
        id=uuid4(),
        campaign_id=campaign_id,
        kind="secret",
        title="Dragon Lair",
        body="There is a sleeping dragon below.",
        state_json={},
        dm_notes="Triggers if players make too much noise.",
        visibility="dm_only",
        needs_review=False,
        character_recipient_ids=(),
        revision=2,
        created_by_actor_kind="dm",
        created_at=now,
        updated_at=now,
    )

    # 1. DM projection receives DM view for all entries
    dm_view_pub = project_runtime_entry(public_entry, controlled_character_ids=(), is_dm=True)
    assert isinstance(dm_view_pub, RuntimeWorldEntryDmView)
    assert dm_view_pub.dm_notes == "Tavern keeper is a retired spy."
    assert dm_view_pub.needs_review is True
    assert dm_view_pub.source_adventure_entry_id == source_entry_id
    assert dm_view_pub.provenance_json == {"origin": "adventure_override"}
    assert dm_view_pub.character_recipient_ids == ()

    dm_view_char = project_runtime_entry(character_entry, controlled_character_ids=(), is_dm=True)
    assert isinstance(dm_view_char, RuntimeWorldEntryDmView)
    assert dm_view_char.dm_notes == "Only Char A was told this in secret."
    assert dm_view_char.character_recipient_ids == (char_a,)

    dm_view_secret = project_runtime_entry(dm_only_entry, controlled_character_ids=(), is_dm=True)
    assert isinstance(dm_view_secret, RuntimeWorldEntryDmView)
    assert dm_view_secret.dm_notes == "Triggers if players make too much noise."
    assert dm_view_secret.visibility == "dm_only"

    # 2. Player projection on public entry
    player_pub = project_runtime_entry(public_entry, controlled_character_ids=(), is_dm=False)
    assert isinstance(player_pub, RuntimeWorldEntryPlayerView)
    assert player_pub.id == public_entry.id
    assert player_pub.campaign_id == campaign_id
    assert player_pub.kind == "scene"
    assert player_pub.title == "Public Tavern"
    assert player_pub.body == "A bustling place."
    assert player_pub.visibility == "public"
    assert player_pub.revision == 3
    assert player_pub.created_at == now
    assert player_pub.updated_at == now

    # 3. Player projection on character entry
    # Matching character
    player_char_own = project_runtime_entry(
        character_entry,
        controlled_character_ids=[char_a],
        is_dm=False,
    )
    assert isinstance(player_char_own, RuntimeWorldEntryPlayerView)
    assert player_char_own.id == character_entry.id
    assert player_char_own.visibility == "character"

    # Non-matching character (other character knowledge -> None)
    player_char_other = project_runtime_entry(
        character_entry,
        controlled_character_ids=[char_b],
        is_dm=False,
    )
    assert player_char_other is None

    # Empty controlled characters -> None
    player_char_none = project_runtime_entry(
        character_entry,
        controlled_character_ids=[],
        is_dm=False,
    )
    assert player_char_none is None

    # 4. Player projection on dm_only entry -> None
    player_secret = project_runtime_entry(
        dm_only_entry,
        controlled_character_ids=[char_a],
        is_dm=False,
    )
    assert player_secret is None

    # 5. STRICT SECURITY CHECK: Player serialized model has NO private fields
    player_serialized = player_pub.model_dump(mode="json")
    forbidden_keys = {
        "dm_notes",
        "provenance",
        "provenance_json",
        "source",
        "source_ref",
        "source_adventure_entry_id",
        "needs_review",
        "recipient",
        "recipient_ids",
        "character_recipient_ids",
        "created_by_actor_kind",
        "created_by_actor_id",
        "archived_at",
    }
    present_forbidden = forbidden_keys.intersection(player_serialized.keys())
    assert not present_forbidden, f"Player view leaked private fields: {present_forbidden}"

    # Expected safe keys only
    expected_safe_keys = {
        "id",
        "campaign_id",
        "kind",
        "title",
        "body",
        "state",
        "visibility",
        "revision",
        "created_at",
        "updated_at",
    }
    assert set(player_serialized.keys()) == expected_safe_keys


def test_projection_does_not_mutate_canonical_entry() -> None:
    now = datetime.now(timezone.utc)
    entry = RuntimeWorldEntry(
        id=uuid4(),
        campaign_id=uuid4(),
        kind="npc",
        title="Original Title",
        body="Original Body",
        state_json={"kind": "npc", "monster_template_ref": "goblin"},
        dm_notes="Original DM Note",
        visibility="public",
        needs_review=False,
        revision=1,
        created_by_actor_kind="dm",
        created_at=now,
        updated_at=now,
    )

    # Project as DM
    dm_view = project_runtime_entry(entry, controlled_character_ids=(), is_dm=True)
    assert isinstance(dm_view, RuntimeWorldEntryDmView)

    # Project as Player
    player_view = project_runtime_entry(entry, controlled_character_ids=(), is_dm=False)
    assert isinstance(player_view, RuntimeWorldEntryPlayerView)

    # Verify canonical entry is unmodified
    assert entry.title == "Original Title"
    assert entry.body == "Original Body"
    assert entry.dm_notes == "Original DM Note"
    assert entry.visibility == "public"
    assert isinstance(entry.state, RuntimeNpcPayload)
    assert entry.state.monster_template_ref == "goblin"
