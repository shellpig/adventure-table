"""M01-K K.6 — feat automation / deferred classification boundary."""

from __future__ import annotations

import m01k_support as S
from app.domain.rules.hit_points import calculate_max_hp
from app.domain.rules.skills import passive_investigation, passive_perception


STATIC_DERIVED_TARGETS = {"max_hp", "passive_perception", "passive_investigation"}
DEFERRED_PREFIX = "deferred_"

# Feats whose prerequisite needs a caster; everything else fits the fighter fixture.
SPELLCASTING_FEATS = {
    "phb2014:feat:elemental-adept",
    "phb2014:feat:spell-sniper",
    "phb2014:feat:war-caster",
}
# A human adds +1 to every ability, so 13s clear the DEX / CHA prerequisites.
CAPABLE = {
    "strength": 15,
    "dexterity": 15,
    "constitution": 14,
    "intelligence": 13,
    "wisdom": 13,
    "charisma": 13,
}


def _classifications(content) -> dict[str, str]:
    return {entry.key: entry.data.get("automation") for entry in S.feat_entries(content)}


# Spell Sniper's cantrip pool is narrowed to attack-roll cantrips, and only some
# source classes have one in the current catalog. Pin a source that does so the
# sweep exercises the feat rather than the auto-filler's option search.
PINNED_NESTED = {
    "phb2014:feat:spell-sniper": {"spell-source": ("srd5.1:class:wizard",)},
}


def _build_for(content, feat_ref: str):
    spec = S.WIZARD_L8 if feat_ref in SPELLCASTING_FEATS else S.FIGHTER_L4
    result, _, _ = S.feat_draft(
        feat_ref,
        spec=spec,
        abilities=CAPABLE,
        nested=PINNED_NESTED.get(feat_ref),
        content=content,
    )
    assert S.issue_codes(result) == set(), feat_ref
    return result.build_candidate


def test_every_phb_feat_carries_a_classification() -> None:
    content = S.registry()
    classifications = _classifications(content)

    assert len(classifications) == 41
    unclassified = sorted(key for key, value in classifications.items() if not value)
    assert unclassified == []
    for key, value in classifications.items():
        assert value == "full" or value == "static_derived" or value.startswith(DEFERRED_PREFIX), key


def test_all_three_classification_buckets_have_members() -> None:
    content = S.registry()
    values = set(_classifications(content).values())

    assert "full" in values
    assert "static_derived" in values
    assert any(value.startswith(DEFERRED_PREFIX) for value in values)


def test_deferred_classification_distinguishes_the_required_substrates() -> None:
    content = S.registry()
    classifications = _classifications(content)
    deferred = {value for value in classifications.values() if value.startswith(DEFERRED_PREFIX)}

    assert {
        "deferred_roll",
        "deferred_combat",
        "deferred_reaction",
        "deferred_rest",
        "deferred_equipment_conditional",
    } <= deferred


def test_static_derived_covers_tough_and_observant() -> None:
    content = S.registry()
    classifications = _classifications(content)
    static = {key for key, value in classifications.items() if value == "static_derived"}

    assert {"phb2014:feat:tough", "phb2014:feat:observant"} <= static


def test_equipment_conditional_bucket_holds_the_equipment_gated_feats() -> None:
    content = S.registry()
    classifications = _classifications(content)
    conditional = {
        key
        for key, value in classifications.items()
        if value == "deferred_equipment_conditional"
    }

    assert {"phb2014:feat:medium-armor-master", "phb2014:feat:dual-wielder"} <= conditional


def test_combat_and_rest_feats_keep_their_original_deferred_buckets() -> None:
    content = S.registry()
    classifications = _classifications(content)

    assert classifications["phb2014:feat:heavy-armor-master"] == "deferred_combat"
    assert classifications["phb2014:feat:durable"] == "deferred_rest"


def test_static_modifier_targets_stay_inside_the_whitelist() -> None:
    content = S.registry()
    for entry in S.feat_entries(content):
        for modifier in entry.data.get("static_modifiers", []):
            assert modifier["target"] in STATIC_DERIVED_TARGETS, entry.key


def test_static_derived_feats_actually_move_the_sheet_numbers() -> None:
    content = S.registry()
    baseline = _build_for(content, "phb2014:feat:alert")

    tough = _build_for(content, "phb2014:feat:tough")
    assert calculate_max_hp(tough) > calculate_max_hp(baseline)

    observant = _build_for(content, "phb2014:feat:observant")
    assert passive_perception(observant, content) > passive_perception(baseline, content)
    assert passive_investigation(observant, content) > passive_investigation(baseline, content)


def test_no_deferred_feat_quietly_changes_a_derived_value() -> None:
    """A ``deferred_*`` feat may grant structure, never a static derived modifier."""

    content = S.registry()
    classifications = _classifications(content)
    offenders: list[str] = []
    for feat_ref, classification in sorted(classifications.items()):
        if classification == "static_derived":
            continue
        build = _build_for(content, feat_ref)
        if build.static_derived_modifiers:
            offenders.append(feat_ref)
    assert offenders == []


def test_deferred_feats_still_persist_identity_and_their_structural_part() -> None:
    content = S.registry()
    for feat_ref in (
        "phb2014:feat:sentinel",
        "phb2014:feat:polearm-master",
        "phb2014:feat:great-weapon-master",
        "phb2014:feat:sharpshooter",
        "phb2014:feat:lucky",
        "phb2014:feat:war-caster",
        "phb2014:feat:mage-slayer",
        "phb2014:feat:defensive-duelist",
    ):
        entry = content.get(feat_ref)
        assert entry.name
        assert entry.data["desc"]
        assert isinstance(entry.data["prerequisites"], list)

        build = _build_for(content, feat_ref)
        assert feat_ref in build.feat_refs
        acquisition = next(item for item in build.feat_acquisitions if item.feat_ref == feat_ref)
        assert acquisition.source_opportunity

        # Declared structural parts still compile; nothing else is invented.
        raw = entry.data
        if isinstance(raw.get("ability_increase"), dict):
            assert acquisition.selections or raw["ability_increase"].get("mode") == "fixed"
        if isinstance(raw.get("resource"), dict):
            assert any(
                grant.source_ref == feat_ref for grant in build.feat_resource_grants
            )
        else:
            assert all(grant.source_ref != feat_ref for grant in build.feat_resource_grants)


def test_lucky_materializes_its_own_pool_without_touching_superiority_dice() -> None:
    from app.domain.rules.feature_resources import feature_resource_capacities

    content = S.registry()
    build = _build_for(content, "phb2014:feat:lucky")
    grant = next(
        item for item in build.feat_resource_grants if item.resource_id == "luck-points"
    )

    assert grant.capacity == 3
    assert grant.recharge == ("long_rest",)
    assert grant.stacking == "separate"
    capacities = feature_resource_capacities(build, content)
    assert capacities[f"feat:{grant.source_ref}:luck-points"] == 3
    assert "feature:superiority-dice" not in capacities


def test_runtime_ignores_a_static_modifier_target_outside_the_whitelist() -> None:
    """Data cannot widen the derived-value whitelist on its own."""

    content = S.registry()
    tough = content.get("phb2014:feat:tough")
    patched_data = dict(tough.data)
    patched_data["static_modifiers"] = [
        {"target": "armor_class", "value": 5, "per_level": False}
    ]
    patched = tough.model_copy(update={"data": patched_data})

    class _PatchedRegistry:
        def __init__(self, inner):
            self._inner = inner

        def get_optional(self, key):
            return patched if key == patched.key else self._inner.get_optional(key)

        def __getattr__(self, name):
            return getattr(self._inner, name)

    from app.domain.character_builder.m01k_feats import compile_feat_acquisitions

    result, payload, _ = S.feat_draft("phb2014:feat:tough", content=content)
    compilation = compile_feat_acquisitions(
        S.draft(payload), _PatchedRegistry(content), result.choices
    )

    assert compilation.static_modifiers == ()
