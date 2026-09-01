from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.content import load_default_content_registry
from app.domain.character_builder.compiler import compile_builder_draft
from app.domain.character_builder.equipment import compile_starting_equipment
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderMode,
    BuilderReferenceSelection,
)


SCAG_KEYS = {
    "scag:background:city-watch",
    "scag:background:investigator",
    "scag:background:clan-crafter",
    "scag:background:cloistered-scholar",
    "scag:background:courtier",
    "scag:background:faction-agent",
    "scag:background:far-traveler",
    "scag:background:inheritor",
    "scag:background:knight-of-the-order",
    "scag:background:mercenary-veteran",
    "scag:background:urban-bounty-hunter",
    "scag:background:uthgardt-tribe-member",
    "scag:background:waterdhavian-noble",
}
GOS_KEYS = {
    "gos:background:fisher",
    "gos:background:marine",
    "gos:background:shipwright",
    "gos:background:smuggler",
}
ROLEPLAY_FIELDS = ("personality_traits", "ideals", "bonds", "flaws")

BACKGROUND_MECHANICAL_MATRIX = {
    "scag:background:city-watch": (2, 0, 0, 2, 1, 0, 10, "Watcher's Eye"),
    "scag:background:investigator": (2, 0, 0, 2, 1, 0, 10, "Watcher's Eye"),
    "scag:background:clan-crafter": (2, 1, 0, 1, 1, 1, 5, "Respect of the Stout Folk"),
    "scag:background:cloistered-scholar": (1, 1, 0, 2, 1, 0, 10, "Library Access"),
    "scag:background:courtier": (2, 0, 0, 2, 1, 0, 5, "Court Functionary"),
    "scag:background:faction-agent": (1, 1, 0, 2, 1, 0, 15, "Safe Haven"),
    "scag:background:far-traveler": (2, 1, 0, 1, 1, 0, 5, "All Eyes on You"),
    "scag:background:inheritor": (1, 1, 1, 1, 1, 0, 15, "Inheritance"),
    "scag:background:knight-of-the-order": (1, 1, 1, 1, 1, 0, 10, "Knightly Regard"),
    "scag:background:mercenary-veteran": (3, 1, 0, 0, 1, 1, 10, "Mercenary Life"),
    "scag:background:urban-bounty-hunter": (0, 2, 2, 0, 1, 0, 20, "Ear to the Ground"),
    "scag:background:uthgardt-tribe-member": (2, 1, 0, 1, 1, 0, 10, "Uthgardt Heritage"),
    "scag:background:waterdhavian-noble": (2, 1, 0, 1, 1, 0, 20, "Kept in Style"),
    "gos:background:fisher": (2, 0, 0, 1, 4, 0, 10, "Harvest the Water"),
    "gos:background:marine": (4, 0, 0, 0, 3, 0, 10, "Steady"),
    "gos:background:shipwright": (4, 0, 0, 0, 4, 0, 10, "I'll Patch It!"),
    "gos:background:smuggler": (3, 0, 0, 0, 2, 0, 15, "Down Low"),
}


def _draft(background_ref: str) -> BuilderDraft:
    now = datetime.now(UTC)
    payload = BuilderDraftPayload(
        basic=BuilderBasicInput(name="M01-C Hero"),
        target_level=1,
        race_selection=BuilderReferenceSelection(reference_id="srd5.1:race:human"),
        background_selection=BuilderReferenceSelection(reference_id=background_ref),
        ability_generation={
            "method": "standard_array",
            "scores": {
                "strength": 15,
                "dexterity": 14,
                "constitution": 13,
                "intelligence": 12,
                "wisdom": 10,
                "charisma": 8,
            },
        },
    )
    return BuilderDraft(
        id=uuid4(),
        mode=BuilderMode.CREATE,
        revision=1,
        draft_payload=payload,
        created_at=now,
        updated_at=now,
    )


def test_default_registry_enables_complete_m01c_background_packs() -> None:
    registry = load_default_content_registry()

    assert registry.enabled_pack_ids == (
        "srd5.1",
        "phb2014",
        "scag",
        "gos",
        "vgm",
        "vrgr",
        "tce",
    )
    assert {entry.key for entry in registry.list_kind("background", source="scag")} == SCAG_KEYS
    assert {entry.key for entry in registry.list_kind("background", source="gos")} == GOS_KEYS

    for key in sorted(SCAG_KEYS | GOS_KEYS):
        entry = registry.get(key)
        assert entry.data["starting_proficiencies"] is not None
        assert isinstance(entry.data["starting_equipment"], list)
        assert entry.data["starting_gold"]["unit"] == "gp"
        assert entry.data["starting_gold"]["quantity"] >= 0
        assert entry.data["feature"]["name"]
        assert entry.source_label in {
            "Sword Coast Adventurer's Guide",
            "Ghosts of Saltmarsh",
        }


@pytest.mark.parametrize("background_key", sorted(BACKGROUND_MECHANICAL_MATRIX))
def test_each_m01c_background_has_expected_mechanical_shape(background_key: str) -> None:
    registry = load_default_content_registry()
    data = registry.get(background_key).data
    (
        fixed_proficiencies,
        primary_proficiency_choose,
        secondary_proficiency_choose,
        language_choose,
        equipment_entries,
        equipment_choice_groups,
        starting_gold,
        feature_name,
    ) = BACKGROUND_MECHANICAL_MATRIX[background_key]

    assert len(data["starting_proficiencies"]) == fixed_proficiencies
    assert data.get("starting_proficiency_options", {}).get("choose", 0) == primary_proficiency_choose
    assert data.get("proficiency_choices", {}).get("choose", 0) == secondary_proficiency_choose
    assert data.get("language_options", {}).get("choose", 0) == language_choose
    assert len(data["starting_equipment"]) == equipment_entries
    assert len(data.get("starting_equipment_options", [])) == equipment_choice_groups
    assert data["starting_gold"] == {"quantity": starting_gold, "unit": "gp"}
    assert data["feature"]["name"] == feature_name


def test_scag_roleplay_inheritance_reuses_only_suggestions() -> None:
    registry = load_default_content_registry()
    city_watch = registry.get("scag:background:city-watch")
    soldier = registry.get("phb2014:background:soldier")

    city_roleplay = city_watch.data["roleplay_suggestions"]
    soldier_roleplay = soldier.data["roleplay_suggestions"]
    assert city_roleplay["inherits_from"] == "phb2014:background:soldier"
    for field in ROLEPLAY_FIELDS:
        assert city_roleplay[field] == soldier_roleplay[field]

    city_proficiencies = {
        item["key"] for item in city_watch.data["starting_proficiencies"]
    }
    soldier_proficiencies = {
        item["key"] for item in soldier.data["starting_proficiencies"]
    }
    assert city_proficiencies == {
        "srd5.1:proficiency:skill-athletics",
        "srd5.1:proficiency:skill-insight",
    }
    assert city_proficiencies != soldier_proficiencies
    assert city_watch.data["feature"]["name"] == "Watcher's Eye"
    assert city_watch.data["starting_gold"]["quantity"] == 10


def test_scag_source_audit_reuse_and_numeric_feature_metadata() -> None:
    registry = load_default_content_registry()

    faction_agent = registry.get("scag:background:faction-agent")
    acolyte = registry.get("phb2014:background:acolyte")
    faction_roleplay = faction_agent.data["roleplay_suggestions"]
    assert faction_roleplay["inherits_from"] == "phb2014:background:acolyte"
    for field in ROLEPLAY_FIELDS:
        assert faction_roleplay[field] == acolyte.data["roleplay_suggestions"][field]
    assert faction_agent.data["feature_metadata"]["safe_haven"] == {
        "hidden_safe_place": True,
        "food_and_lodging_cost": "free",
        "information_assistance": True,
        "contacts_risk_lives_or_identity": False,
        "automation": "manual",
    }

    inheritor = registry.get("scag:background:inheritor")
    folk_hero = registry.get("phb2014:background:folk-hero")
    inheritor_roleplay = inheritor.data["roleplay_suggestions"]
    assert inheritor_roleplay["inherits_from"] == "phb2014:background:folk-hero"
    for field in ROLEPLAY_FIELDS:
        assert inheritor_roleplay[field] == folk_hero.data["roleplay_suggestions"][field]

    uthgardt = registry.get("scag:background:uthgardt-tribe-member")
    assert uthgardt.data["feature_metadata"]["foraging"] == {
        "food_and_water_multiplier": 2,
        "automation": "manual",
    }
    assert uthgardt.data["feature_metadata"]["hospitality"][
        "from_uthgardt_and_allies"
    ] is True


def test_scag_variant_identity_and_independent_skill_tool_choices() -> None:
    registry = load_default_content_registry()
    investigator = registry.get("scag:background:investigator")
    assert investigator.data["variant_of"]["key"] == "scag:background:city-watch"

    result = compile_builder_draft(_draft("scag:background:inheritor"), registry)
    inheritor_choices = [
        choice for choice in result.choices if choice.source_ref == "scag:background:inheritor"
    ]
    by_source = {choice.option_source: choice for choice in inheritor_choices}

    assert by_source["content:starting_proficiency_options"].choose_count == 1
    assert {
        option.reference_id
        for option in by_source["content:starting_proficiency_options"].options
    } == {
        "srd5.1:proficiency:skill-arcana",
        "srd5.1:proficiency:skill-history",
        "srd5.1:proficiency:skill-religion",
    }
    assert by_source["content:proficiency_choices"].choose_count == 1
    assert all(
        option.reference_id and option.reference_id.startswith("srd5.1:proficiency:")
        for option in by_source["content:proficiency_choices"].options
    )
    assert by_source["content:language_options"].choose_count == 1


def test_background_selector_is_source_aware_for_scag_and_gos() -> None:
    registry = load_default_content_registry()
    result = compile_builder_draft(
        BuilderDraft(
            id=uuid4(),
            mode=BuilderMode.CREATE,
            revision=1,
            draft_payload=BuilderDraftPayload(),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        ),
        registry,
    )
    selector = next(
        choice for choice in result.choices if choice.option_source == "content:background"
    )
    labels = {option.option_id: option.label for option in selector.options}

    assert "Noble · Player's Handbook 2014 Additions" in labels.values()
    assert labels["scag:background:waterdhavian-noble"].endswith(
        "· Sword Coast Adventurer's Guide"
    )
    assert labels["gos:background:fisher"].endswith("· Ghosts of Saltmarsh")
    assert "scag:background:city-watch" in labels
    assert "gos:background:marine" in labels


def test_gos_flavor_tables_are_optional_and_not_builder_choices() -> None:
    registry = load_default_content_registry()
    fisher = registry.get("gos:background:fisher")
    marine = registry.get("gos:background:marine")

    assert len(fisher.data["optional_roleplay_tables"]["fishing_tale"]) == 8
    assert len(marine.data["optional_roleplay_tables"]["hardship_endured"]) == 6

    result = compile_builder_draft(_draft("gos:background:fisher"), registry)
    fisher_choices = [
        choice for choice in result.choices if choice.source_ref == "gos:background:fisher"
    ]
    assert {choice.option_source for choice in fisher_choices} == {
        "content:language_options"
    }
    assert not any("roleplay" in choice.option_source for choice in fisher_choices)


def test_gos_background_equipment_compiles_deterministically_without_duplication() -> None:
    registry = load_default_content_registry()
    draft = _draft("gos:background:fisher")

    first = compile_starting_equipment(draft, registry)
    second = compile_starting_equipment(draft, registry)

    expected = {
        "srd5.1:equipment:fishing-tackle",
        "srd5.1:equipment:net",
        "srd5.1:equipment:clothes-travelers",
        "srd5.1:equipment:pouch",
    }
    assert {entry.item_ref for entry in first.starting_equipment} == expected
    assert first.starting_equipment == second.starting_equipment
    assert len(first.starting_equipment) == len(
        {entry.entry_id for entry in first.starting_equipment}
    )
    assert first.issues == ()