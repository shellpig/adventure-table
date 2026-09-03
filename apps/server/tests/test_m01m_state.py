"""M01-M M.7 / M.8 — conditional movement and feature modes are Current State."""

from __future__ import annotations

import pytest

import m01k_support as S
import m01m_support as M

from app.content import load_default_content_registry
from app.content.m01m_models import FeatureModeData
from app.domain.character.schemas import AbilityScores, CharacterBuild, CharacterState, SubclassSelection
from app.domain.rules.artificer import (
    ARMOR_MODEL_FEATURE_REF,
    ARMOR_MODELS,
    ARMORER_REF,
    ARTIFICER_REF,
    ELDRITCH_CANNON_FEATURE_REF,
    ELDRITCH_CANNON_TYPES,
)
from app.domain.rules.m01m_ancestry import validate_feature_modes


ELADRIN = "mtf:subrace:eladrin"
SEA_ELF = "mtf:subrace:sea-elf"
SEASON_MODE = "eladrin-season"
SEASONS = ("autumn", "winter", "spring", "summer")

CHAIN_MAIL = "srd5.1:equipment:chain-mail"
LEATHER_ARMOR = "srd5.1:equipment:leather-armor"


def _winged_payload(name: str = "Winged Tiefling"):
    return M.with_variant(
        M.base_payload(race=M.TIEFLING, name=name),
        M.SCAG_TIEFLING_VARIANT,
        options={"ability-package": "feral", "legacy": "winged"},
    )


def _equip(client, character_id: str, item_ref: str | None):
    """Replace the equipped body armor, returning the refreshed sheet."""

    character = client.get(f"/api/characters/{character_id}").json()
    inventory = [
        entry
        for entry in character["state"]["inventory_state"]
        if entry["item_ref"] not in {CHAIN_MAIL, LEATHER_ARMOR}
    ]
    if item_ref is not None:
        inventory.append(
            {
                "entry_id": f"inventory:test:{item_ref}",
                "item_ref": item_ref,
                "quantity": 1,
                "equipped": True,
            }
        )
    response = client.patch(
        f"/api/characters/{character_id}/state",
        json={"inventory_state": inventory},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_winged_flight_is_state_derived_and_never_frozen_into_the_build() -> None:
    content = S.registry()
    client, engine = S.seed_http()
    try:
        created = M.http_create_character(client, _winged_payload(), content)
        character_id = created["character_id"]

        # M.7 Build ownership: the Build must not assert a speed that is only
        # true for some equipment states.
        build = client.get(f"/api/characters/{character_id}").json()["build"]
        assert build["fly_speed"] is None
        assert "scag:feature:winged-tiefling" in build["feature_refs"]

        assert client.get(f"/api/characters/{character_id}/sheet").json()["fly_speed"] == 30

        assert _equip(client, character_id, CHAIN_MAIL)["fly_speed"] is None
        # A body armor that is not heavy leaves the flight intact.
        assert _equip(client, character_id, LEATHER_ARMOR)["fly_speed"] == 30
        assert _equip(client, character_id, None)["fly_speed"] == 30
    finally:
        client.close()


def test_equipping_armor_never_creates_a_character_version() -> None:
    content = S.registry()
    client, engine = S.seed_http()
    try:
        created = M.http_create_character(client, _winged_payload(), content)
        character_id = created["character_id"]
        before = client.get(f"/api/characters/{character_id}").json()

        _equip(client, character_id, CHAIN_MAIL)
        _equip(client, character_id, None)

        after = client.get(f"/api/characters/{character_id}").json()
        assert after["version_no"] == before["version_no"]
        assert after["current_version_id"] == before["current_version_id"]
        assert len(client.get(f"/api/characters/{character_id}/versions").json()) == 1
    finally:
        client.close()


def test_conditional_flight_survives_a_restart_from_build_plus_state() -> None:
    content = S.registry()
    client, engine = S.seed_http()
    try:
        created = M.http_create_character(client, _winged_payload(), content)
        character_id = created["character_id"]
        assert _equip(client, character_id, CHAIN_MAIL)["fly_speed"] is None

        client = S.rebind_http(engine)
        assert client.get(f"/api/characters/{character_id}/sheet").json()["fly_speed"] is None

        assert _equip(client, character_id, None)["fly_speed"] == 30
        client = S.rebind_http(engine)
        assert client.get(f"/api/characters/{character_id}/sheet").json()["fly_speed"] == 30
    finally:
        client.close()


def test_unconditional_movement_is_untouched_by_equipment() -> None:
    content = S.registry()
    payload = M.with_subrace(M.base_payload(race=M.ELF, name="Sea Elf"), SEA_ELF)

    client, engine = S.seed_http()
    try:
        created = M.http_create_character(client, payload, content)
        character_id = created["character_id"]

        assert client.get(f"/api/characters/{character_id}").json()["build"]["swim_speed"] == 30
        assert _equip(client, character_id, CHAIN_MAIL)["swim_speed"] == 30
        assert _equip(client, character_id, None)["swim_speed"] == 30
    finally:
        client.close()


@pytest.mark.parametrize("season", SEASONS)
def test_initial_state_seed_picks_a_legal_season_that_stays_out_of_the_build(season: str) -> None:
    content = S.registry()
    payload = M.with_subrace(M.base_payload(race=M.ELF, name="Eladrin"), ELADRIN)
    payload = payload.model_copy(
        update={"initial_state_seed": {"feature_modes": {SEASON_MODE: season}}}
    )

    client, engine = S.seed_http()
    try:
        created = M.http_create_character(client, payload, content)
        character = client.get(f"/api/characters/{created['character_id']}").json()

        assert character["state"]["feature_modes"] == {SEASON_MODE: season}
        assert SEASON_MODE not in character["build"]
        assert "mtf:feature:eladrin-seasonal-aspect" in character["build"]["feature_refs"]
    finally:
        client.close()


def test_changing_season_only_touches_state_and_survives_restart() -> None:
    content = S.registry()
    payload = M.with_subrace(M.base_payload(race=M.ELF, name="Eladrin"), ELADRIN)

    client, engine = S.seed_http()
    try:
        created = M.http_create_character(client, payload, content)
        character_id = created["character_id"]
        before = client.get(f"/api/characters/{character_id}").json()

        for season in SEASONS:
            response = client.patch(
                f"/api/characters/{character_id}/state",
                json={"feature_modes": {SEASON_MODE: season}},
            )
            assert response.status_code == 200, response.text
            assert response.json()["feature_modes"][SEASON_MODE] == season

        after = client.get(f"/api/characters/{character_id}").json()
        assert after["version_no"] == before["version_no"]
        assert after["current_version_id"] == before["current_version_id"]

        client = S.rebind_http(engine)
        reloaded = client.get(f"/api/characters/{character_id}").json()
        assert reloaded["state"]["feature_modes"][SEASON_MODE] == "summer"
    finally:
        client.close()


@pytest.mark.parametrize(
    "modes",
    [
        {SEASON_MODE: "monsoon"},
        {SEASON_MODE: ""},
        # Default-deny: a mode key the Build does not declare is not a mode.
        {"mtf:feature:eladrin-seasonal-aspect": "summer"},
        {ARMOR_MODEL_FEATURE_REF: "guardian"},
        {"totally-made-up": "value"},
    ],
)
def test_state_rejects_modes_the_build_does_not_declare(modes: dict[str, str]) -> None:
    content = S.registry()
    payload = M.with_subrace(M.base_payload(race=M.ELF, name="Eladrin"), ELADRIN)

    client, engine = S.seed_http()
    try:
        created = M.http_create_character(client, payload, content)
        character_id = created["character_id"]

        response = client.patch(
            f"/api/characters/{character_id}/state",
            json={"feature_modes": modes},
        )
        assert response.status_code == 422, response.text

        # A refused mode change leaves the stored state exactly as it was.
        stored = client.get(f"/api/characters/{character_id}").json()
        assert stored["state"]["feature_modes"] == {SEASON_MODE: "autumn"}
    finally:
        client.close()


def _artificer_build(
    *,
    level: int,
    subclass_ref: str | None,
    feature_refs: tuple[str, ...],
) -> CharacterBuild:
    return CharacterBuild(
        content_sources=("srd5.1", "tce"),
        race_ref="srd5.1:race:human",
        character_level=level,
        class_progression=(ARTIFICER_REF,) * level,
        subclasses=(
            (SubclassSelection(class_ref=ARTIFICER_REF, subclass_ref=subclass_ref),)
            if subclass_ref is not None
            else ()
        ),
        ability_scores=AbilityScores(
            strength=10,
            dexterity=14,
            constitution=10,
            intelligence=14,
            wisdom=10,
            charisma=10,
        ),
        feature_refs=feature_refs,
        hp_progression=(8,) + (5,) * (level - 1),
    )


def _state_with(build: CharacterBuild, modes: dict[str, str]) -> CharacterState:
    return CharacterState(
        current_hp=8 + 5 * (build.character_level - 1),
        hit_dice_state={"d8": build.character_level},
        feature_modes=modes,
    )


@pytest.mark.parametrize(
    ("feature_ref", "subclass_ref", "mode"),
    [
        (ARMOR_MODEL_FEATURE_REF, ARMORER_REF, "guardian"),
        (ELDRITCH_CANNON_FEATURE_REF, "tce:subclass:artillerist", "flamethrower"),
    ],
)
def test_artificer_modes_go_through_the_shared_validator(
    feature_ref: str,
    subclass_ref: str,
    mode: str,
) -> None:
    registry = load_default_content_registry()

    granted = _artificer_build(level=3, subclass_ref=subclass_ref, feature_refs=(feature_ref,))
    validate_feature_modes(granted, _state_with(granted, {feature_ref: mode}), registry)

    with pytest.raises(ValueError, match="invalid feature mode"):
        validate_feature_modes(granted, _state_with(granted, {feature_ref: "nonsense"}), registry)

    # The subclass + level prerequisite now falls out of the Build not granting
    # the feature at all, rather than a hardcoded per-feature check.
    ungranted = _artificer_build(level=2, subclass_ref=None, feature_refs=())
    with pytest.raises(ValueError, match="not granted by the current Build"):
        validate_feature_modes(ungranted, _state_with(ungranted, {feature_ref: mode}), registry)


@pytest.mark.parametrize(
    ("feature_ref", "expected"),
    [
        (ARMOR_MODEL_FEATURE_REF, ARMOR_MODELS),
        (ELDRITCH_CANNON_FEATURE_REF, ELDRITCH_CANNON_TYPES),
    ],
)
def test_artificer_mode_content_matches_the_options_the_dto_offers(
    feature_ref: str,
    expected: tuple[str, ...],
) -> None:
    registry = load_default_content_registry()
    descriptor = FeatureModeData.model_validate(registry.get(feature_ref).data["feature_mode"])

    assert descriptor.mode_key == feature_ref
    assert descriptor.options == expected
