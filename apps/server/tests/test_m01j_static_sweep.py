from __future__ import annotations

from app.content import load_default_content_registry
from app.domain.character.schemas import AbilityScores, CharacterBuild, SubclassSelection
from app.domain.rules.feature_resources import feature_resource_capacities


LAND_REF = "srd5.1:subclass:land"
SHEPHERD_REF = "xge:subclass:shepherd"
STARS_REF = "tce:subclass:stars"
ARCANA_REF = "scag:subclass:arcana"
DRUID_REF = "srd5.1:class:druid"


def _choice_by_key(subclass, key: str):
    return next(
        row
        for row in subclass.data.get("grant_choices", [])
        if isinstance(row, dict) and row.get("choice_key") == key
    )


def _spell_row(subclass, spell_ref: str):
    return next(
        row
        for row in subclass.data.get("spells", [])
        if isinstance(row, dict)
        and isinstance(row.get("spell"), dict)
        and row["spell"].get("key") == spell_ref
    )


def test_land_bonus_cantrip_uses_generic_druid_cantrip_grant_pool() -> None:
    registry = load_default_content_registry()
    choice = _choice_by_key(registry.get(LAND_REF), "land-bonus-cantrip")
    assert choice["minimum_class_level"] == 2
    assert choice["choose_total"] == 1
    assert choice["grant_target"] == "spell"
    assert choice["option_pool"] == "druid_cantrips"
    assert choice["access_type"] == "granted"


def test_shepherd_speech_of_the_woods_grants_sylvan() -> None:
    registry = load_default_content_registry()
    fixed = registry.get(SHEPHERD_REF).data["fixed_grants"]
    assert "srd5.1:language:sylvan" in fixed["languages"]


def test_stars_star_map_grants_guiding_bolt_and_pb_long_rest_resource() -> None:
    registry = load_default_content_registry()
    subclass = registry.get(STARS_REF)
    row = _spell_row(subclass, "srd5.1:spell:guiding-bolt")
    assert row["access_type"] == "always_prepared"

    star_map = next(
        feature
        for feature in registry.list_kind("feature")
        if feature.name == "Star Map"
        and isinstance(feature.data.get("subclass"), dict)
        and feature.data["subclass"].get("key") == STARS_REF
    )
    assert star_map.data["resource"] == {
        "capacity": {"type": "proficiency_bonus"},
        "recharge": ["long_rest"],
    }

    build = CharacterBuild(
        race_ref="srd5.1:race:human",
        character_level=9,
        class_progression=(DRUID_REF,) * 9,
        subclasses=(SubclassSelection(class_ref=DRUID_REF, subclass_ref=STARS_REF),),
        ability_scores=AbilityScores(
            strength=10,
            dexterity=10,
            constitution=10,
            intelligence=10,
            wisdom=16,
            charisma=10,
        ),
        feature_refs=(star_map.key,),
        hp_progression=(8, 5, 5, 5, 5, 5, 5, 5, 5),
    )
    capacities = feature_resource_capacities(build, registry)
    assert capacities[f"feature:{star_map.key}"] == 4


def test_arcana_domain_keeps_arcana_skill_proficiency() -> None:
    registry = load_default_content_registry()
    fixed = registry.get(ARCANA_REF).data["fixed_grants"]
    assert "srd5.1:skill:arcana" in fixed["skills"]
