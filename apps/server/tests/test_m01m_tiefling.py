"""M01-M M.4 / M.5 / M.6 / M.11 — bloodline replacement, SCAG composition, persistence."""

from __future__ import annotations

from uuid import uuid4

import pytest

import m01k_support as S
import m01m_support as M

from app.content import load_default_content_registry
from app.domain.character.schemas import CharacterBuild, PersistedCharacter
from app.domain.character_builder.creation import build_initial_character_state
from app.domain.character_builder.schemas import BuilderChoiceSelection, BuilderMode
from app.domain.character_builder.versions import seed_version_draft_payload


ASMODEUS_BASELINE = "srd5.1:race:tiefling"
INFERNAL_LEGACY = "srd5.1:trait:infernal-legacy"

# (variant, option id, granted legacy, the ability the bloodline puts +1 on)
BLOODLINES = [
    ("mtf:race-variant:baalzebul-tiefling", "baalzebul", "mtf:feature:legacy-of-baalzebul", "intelligence"),
    ("mtf:race-variant:dispater-tiefling", "dispater", "mtf:feature:legacy-of-dispater", "dexterity"),
    ("mtf:race-variant:fierna-tiefling", "fierna", "mtf:feature:legacy-of-fierna", "wisdom"),
    ("mtf:race-variant:glasya-tiefling", "glasya", "mtf:feature:legacy-of-glasya", "dexterity"),
    ("mtf:race-variant:levistus-tiefling", "levistus", "mtf:feature:legacy-of-levistus", "constitution"),
    ("mtf:race-variant:mammon-tiefling", "mammon", "mtf:feature:legacy-of-mammon", "intelligence"),
    ("mtf:race-variant:mephistopheles-tiefling", "mephistopheles", "mtf:feature:legacy-of-mephistopheles", "intelligence"),
    ("mtf:race-variant:zariel-tiefling", "zariel", "mtf:feature:legacy-of-zariel", "strength"),
]


def _baseline_abilities() -> dict[str, int]:
    result, _ = M.ancestry(race=M.TIEFLING)
    return M.effective_abilities(result)


@pytest.mark.parametrize(("variant", "option", "legacy", "raised"), BLOODLINES)
def test_bloodline_replaces_both_standard_packages_without_stacking(
    variant: str,
    option: str,
    legacy: str,
    raised: str,
) -> None:
    result, _ = M.ancestry(race=M.TIEFLING, variant=variant, options={"bloodline": option})
    build = result.build_candidate

    assert result.validation.issues == ()
    assert build is not None
    assert build.race_ref == ASMODEUS_BASELINE
    assert build.race_variant_ref == variant

    # The Legacy package is replaced, not added alongside the standard one.
    granted = M.grant_refs(result)
    assert legacy in build.feature_refs
    assert INFERNAL_LEGACY not in granted
    assert INFERNAL_LEGACY not in build.feature_refs

    # The ability package is replaced through the group flag, so no invented
    # ability-score-increase grant identity may appear in the summary.
    assert not [ref for ref in granted if "ability-score-increase" in ref]

    # Common Tiefling traits still come from the base race, exactly once.
    assert granted.count("srd5.1:language:infernal") == 1
    assert build.walking_speed == 30


@pytest.mark.parametrize(("variant", "option", "legacy", "raised"), BLOODLINES)
def test_bloodline_ability_package_is_not_added_on_top_of_the_standard_one(
    variant: str,
    option: str,
    legacy: str,
    raised: str,
) -> None:
    baseline = _baseline_abilities()
    result, _ = M.ancestry(race=M.TIEFLING, variant=variant, options={"bloodline": option})
    abilities = M.effective_abilities(result)

    # Every bloodline is CHA +2 plus one other +1. Charisma therefore matches the
    # standard package, and the standard Intelligence +1 must be gone unless this
    # bloodline is the one that raises Intelligence.
    assert abilities["charisma"] == baseline["charisma"]
    if raised == "intelligence":
        assert abilities["intelligence"] == baseline["intelligence"]
    else:
        assert abilities[raised] == baseline[raised] + 1
        assert abilities["intelligence"] == baseline["intelligence"] - 1


@pytest.mark.parametrize(("variant", "option", "legacy", "raised"), BLOODLINES)
def test_bloodline_legacy_spells_replace_the_standard_infernal_list(
    variant: str,
    option: str,
    legacy: str,
    raised: str,
) -> None:
    standard, _ = M.ancestry(race=M.TIEFLING, level=5)
    bloodline, _ = M.ancestry(
        race=M.TIEFLING, variant=variant, options={"bloodline": option}, level=5
    )

    standard_sources = {entry.source_key for entry in standard.build_candidate.spell_access_entries}
    bloodline_entries = bloodline.build_candidate.spell_access_entries
    bloodline_sources = {entry.source_key for entry in bloodline_entries}

    assert INFERNAL_LEGACY in standard_sources
    assert INFERNAL_LEGACY not in bloodline_sources
    assert legacy in bloodline_sources
    assert all(entry.entry_id for entry in bloodline_entries)


def test_builder_offers_nine_tiefling_variants_and_no_duplicate_asmodeus() -> None:
    payload = M.base_payload(race=M.TIEFLING)
    result, _ = S.compile_payload(payload)
    choice = S.choice_by_source(result, "content:race-variant")

    option_ids = [option.option_id for option in choice.options]
    assert len(option_ids) == 9
    assert M.SCAG_TIEFLING_VARIANT in option_ids
    assert not [option for option in option_ids if "asmodeus" in option]
    # The variant is optional: the standard Tiefling stays selectable as itself.
    assert choice.required is False


@pytest.mark.parametrize(
    "options",
    [
        {},
        {"ability-package": "feral"},
        {"legacy": "devils-tongue"},
        {"legacy": "hellfire"},
        {"legacy": "winged"},
        {"ability-package": "feral", "legacy": "devils-tongue"},
        {"ability-package": "feral", "legacy": "hellfire"},
        {"ability-package": "feral", "legacy": "winged"},
    ],
)
def test_scag_ability_and_legacy_groups_compose_independently(options: dict[str, str]) -> None:
    result, _ = M.ancestry(
        race=M.TIEFLING, variant=M.SCAG_TIEFLING_VARIANT, options=options or None
    )

    assert result.validation.issues == ()
    build = result.build_candidate
    assert build is not None
    assert build.race_variant_ref == M.SCAG_TIEFLING_VARIANT

    selected = {
        group.replacement_group_id: group.selected_option_id
        for group in build.race_variant_group_selections
    }
    for group_id, option_id in options.items():
        assert selected[group_id] == option_id


def test_feral_replaces_the_standard_ability_package_only() -> None:
    baseline = _baseline_abilities()
    result, _ = M.ancestry(
        race=M.TIEFLING,
        variant=M.SCAG_TIEFLING_VARIANT,
        options={"ability-package": "feral"},
    )
    abilities = M.effective_abilities(result)

    assert abilities["dexterity"] == baseline["dexterity"] + 2
    assert abilities["charisma"] == baseline["charisma"] - 2
    assert abilities["intelligence"] == baseline["intelligence"]
    # Feral touches abilities only; the Legacy group is untouched.
    assert INFERNAL_LEGACY in M.grant_refs(result)


@pytest.mark.parametrize("pair", [("hellfire", "winged"), ("devils-tongue", "hellfire")])
def test_two_options_in_the_same_replacement_group_are_blocking(pair: tuple[str, str]) -> None:
    payload = M.with_variant(M.base_payload(race=M.TIEFLING), M.SCAG_TIEFLING_VARIANT)
    choice_id = M.group_choice_id(M.SCAG_TIEFLING_VARIANT, "legacy")
    payload = S.with_selections(
        payload,
        {
            choice_id: BuilderChoiceSelection(
                choice_id=choice_id,
                source_ref=M.SCAG_TIEFLING_VARIANT,
                selected_option_ids=pair,
            )
        },
    )
    result, _ = M.complete(payload)

    assert "invalid_choice_count" in {issue.code for issue in result.validation.issues}
    assert result.build_candidate is None


@pytest.mark.parametrize(
    ("variant", "option", "scag_group", "scag_option"),
    [
        ("mtf:race-variant:baalzebul-tiefling", "baalzebul", "ability-package", "feral"),
        ("mtf:race-variant:dispater-tiefling", "dispater", "legacy", "winged"),
        ("mtf:race-variant:zariel-tiefling", "zariel", "legacy", "devils-tongue"),
    ],
)
def test_cross_book_tiefling_combinations_are_rejected(
    variant: str,
    option: str,
    scag_group: str,
    scag_option: str,
) -> None:
    payload = M.with_variant(
        M.base_payload(race=M.TIEFLING), variant, options={"bloodline": option}
    )
    forged_id = M.group_choice_id(M.SCAG_TIEFLING_VARIANT, scag_group)
    payload = S.with_selections(
        payload,
        {
            forged_id: BuilderChoiceSelection(
                choice_id=forged_id,
                source_ref=M.SCAG_TIEFLING_VARIANT,
                selected_option_ids=(scag_option,),
            )
        },
    )
    result, _ = M.complete(payload)

    issues = {issue.code for issue in result.validation.issues}
    assert "cross_variant_choice_selection" in issues

    # Option generation never offered the combination in the first place.
    offered = {
        choice.source_ref
        for choice in result.choices
        if choice.option_source == "content:race-variant-replacement"
    }
    assert offered == {variant}


def test_forged_cross_book_payload_cannot_confirm_and_creates_nothing() -> None:
    content = S.registry()
    payload = M.with_variant(
        M.base_payload(race=M.TIEFLING),
        "mtf:race-variant:zariel-tiefling",
        options={"bloodline": "zariel"},
    )
    forged_id = M.group_choice_id(M.SCAG_TIEFLING_VARIANT, "ability-package")
    payload = S.with_selections(
        payload,
        {
            forged_id: BuilderChoiceSelection(
                choice_id=forged_id,
                source_ref=M.SCAG_TIEFLING_VARIANT,
                selected_option_ids=("feral",),
            )
        },
    )

    client, _ = S.seed_http()
    try:
        view = S.http_create_draft(client, M.http_ready_payload(payload, content))
        assert "cross_variant_choice_selection" in {
            issue["code"] for issue in view["validation"]["issues"]
        }

        review = client.get(f"/api/character-builder/drafts/{view['draft']['id']}/review")
        assert review.json()["can_confirm"] is False

        S.http_confirm(client, view, expect=422)
        assert client.get("/api/characters").json() == []
    finally:
        client.close()


def test_group_selections_persist_through_confirm_reload_and_build_edit() -> None:
    content = S.registry()
    payload = M.with_variant(
        M.base_payload(race=M.TIEFLING, name="Feral Winged"),
        M.SCAG_TIEFLING_VARIANT,
        options={"ability-package": "feral", "legacy": "winged"},
    )

    client, engine = S.seed_http()
    try:
        created = M.http_create_character(client, payload, content)
        character_id = created["character_id"]
        assert created["version_no"] == 1

        # A restart-equivalent rebind proves the branches came back from storage.
        client = S.rebind_http(engine)
        build = client.get(f"/api/characters/{character_id}").json()["build"]
        assert build["race_variant_ref"] == M.SCAG_TIEFLING_VARIANT
        assert {
            group["replacement_group_id"]: group["selected_option_id"]
            for group in build["race_variant_group_selections"]
        } == {"ability-package": "feral", "legacy": "winged"}

        edit = client.post(
            f"/api/character-builder/characters/{character_id}/drafts",
            json={"mode": "build_edit"},
        )
        assert edit.status_code == 201, edit.text
        seeded = edit.json()["draft"]["draft_payload"]

        assert seeded["race_variant_selection"]["reference_id"] == M.SCAG_TIEFLING_VARIANT
        restored = {
            record["selected_option_ids"][0]
            for choice_id, record in seeded["choice_selections"].items()
            if choice_id.startswith(f"race-variant:{M.SCAG_TIEFLING_VARIANT}:")
        }
        assert restored == {"feral", "winged"}
    finally:
        client.close()


def test_switching_branch_leaves_no_stale_grant_in_the_new_build() -> None:
    winged, _ = M.ancestry(
        race=M.TIEFLING,
        variant=M.SCAG_TIEFLING_VARIANT,
        options={"ability-package": "feral", "legacy": "winged"},
    )
    switched, _ = M.ancestry(
        race=M.TIEFLING,
        variant=M.SCAG_TIEFLING_VARIANT,
        options={"ability-package": "standard-ability-package", "legacy": "hellfire"},
    )

    assert "scag:feature:winged-tiefling" in winged.build_candidate.feature_refs
    assert "scag:feature:winged-tiefling" not in switched.build_candidate.feature_refs
    assert "scag:feature:feral-tiefling" not in switched.build_candidate.feature_refs
    assert "scag:feature:hellfire-tiefling" in switched.build_candidate.feature_refs
    assert M.effective_abilities(switched) == _baseline_abilities()


def test_appearance_suggestions_are_optional_roleplay_and_change_no_legality() -> None:
    registry = load_default_content_registry()
    suggestions = registry.get(M.SCAG_TIEFLING_VARIANT).data["appearance_suggestions"]
    assert len(suggestions) >= 8

    without, _ = M.ancestry(
        race=M.TIEFLING, variant=M.SCAG_TIEFLING_VARIANT, options={"legacy": "hellfire"}
    )
    assert without.validation.issues == ()
    assert without.build_candidate.roleplay_profile.appearance is None

    payload = M.with_variant(
        M.base_payload(race=M.TIEFLING), M.SCAG_TIEFLING_VARIANT, options={"legacy": "hellfire"}
    )
    payload = payload.model_copy(update={"roleplay_profile": {"appearance": suggestions[0]}})
    withtext, _ = M.complete(payload)

    assert withtext.validation.issues == ()
    assert withtext.build_candidate.roleplay_profile.appearance == suggestions[0]
    # Roleplay text must not become a structural selection.
    assert withtext.build_candidate.race_variant_group_selections == (
        without.build_candidate.race_variant_group_selections
    )


def test_an_m01e_build_predating_group_provenance_still_reads_and_seeds() -> None:
    """M.6 backward compatibility: no bulk rewrite of immutable history.

    An M01-E Build was stored before ``race_variant_group_selections`` existed.
    It must still load, and a Build Edit seeded from it must keep the branch the
    old payload recorded rather than reverse engineering it from resolved values.
    """

    registry = S.registry()
    result, payload = M.ancestry(
        race="srd5.1:race:half-elf",
        variant="scag:race-variant:half-elf-wood-descent",
        options={"half-elf-ancestry": "fleet-of-foot"},
    )
    assert result.validation.issues == ()
    assert result.build_candidate.walking_speed == 35

    stored = result.build_candidate.model_dump(mode="json")
    del stored["race_variant_group_selections"]
    old_build = CharacterBuild.model_validate(stored)
    assert old_build.race_variant_group_selections == ()
    assert old_build.race_variant_ref == "scag:race-variant:half-elf-wood-descent"

    character = PersistedCharacter(
        id=uuid4(),
        name="Legacy Half-Elf",
        ruleset=old_build.ruleset,
        current_version_id=uuid4(),
        version_no=1,
        build=old_build,
        state=build_initial_character_state(old_build, registry),
    )
    seeded = seed_version_draft_payload(
        character,
        registry,
        mode=BuilderMode.BUILD_EDIT,
        source_payload=payload,
    )

    assert seeded.race_variant_selection.reference_id == (
        "scag:race-variant:half-elf-wood-descent"
    )
    assert any(
        selection.selected_option_ids == ("fleet-of-foot",)
        for selection in seeded.choice_selections.values()
    )
