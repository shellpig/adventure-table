from __future__ import annotations

from fastapi.testclient import TestClient
from sqlalchemy import func, select, update

from app.domain.character.schemas import (
    CharacterBuild,
    CharacterState,
    ResourceCounter,
    SpellAccessEntry,
)
from app.main import app
from app.persistence.characters import character_states, character_versions, characters
from app.persistence.combat.tables import combat_actions
from app.persistence.rooms.p3c_runtime import roll_requests
from app.persistence.rooms.table_runtime import session_events
from tests.test_p4e_spells_reactions_routes import combat_routes_fixture  # noqa: F401


def _spell_list_url(table, entry_id) -> str:
    return (
        f"/api/rooms/{table.room_id}/campaigns/{table.campaign_id}"
        f"/sessions/{table.session_id}/combat/entries/{entry_id}/spells"
    )


def _add_castable_cantrip_and_unprepared_spell(table) -> None:
    with table.engine.begin() as connection:
        version_id = connection.scalar(
            select(characters.c.current_version_id).where(
                characters.c.id == table.character_id
            )
        )
        build_row = connection.execute(
            select(character_versions.c.build_payload).where(
                character_versions.c.id == version_id
            )
        ).mappings().one()
        build = CharacterBuild.model_validate(build_row["build_payload"])
        additions = (
            SpellAccessEntry(
                entry_id="wizard:fire-bolt",
                spell_key="srd5.1:spell:fire-bolt",
                source_type="class",
                source_key="srd5.1:class:wizard",
                access_type="always_prepared",
            ),
            SpellAccessEntry(
                entry_id="wizard:detect-magic-unprepared",
                spell_key="srd5.1:spell:detect-magic",
                source_type="class",
                source_key="srd5.1:class:wizard",
                access_type="spellbook",
            ),
        )
        existing_ids = {item.entry_id for item in build.spell_access_entries}
        next_build = build.model_copy(
            update={
                "spell_access_entries": (
                    *build.spell_access_entries,
                    *(item for item in additions if item.entry_id not in existing_ids),
                )
            },
            deep=True,
        )
        connection.execute(
            update(character_versions)
            .where(character_versions.c.id == version_id)
            .values(build_payload=next_build.model_dump(mode="json"))
        )


def _exhaust_character_slot_level(table, level: int) -> None:
    with table.engine.begin() as connection:
        state_row = connection.execute(
            select(
                character_states.c.state_payload,
                character_states.c.state_revision,
            ).where(character_states.c.character_id == table.character_id)
        ).mappings().one()
        state = CharacterState.model_validate(state_row["state_payload"])
        current = state.spell_slots[level]
        slots = dict(state.spell_slots)
        slots[level] = ResourceCounter(
            used=current.used + current.remaining,
            remaining=0,
        )
        next_state = state.model_copy(update={"spell_slots": slots}, deep=True)
        connection.execute(
            update(character_states)
            .where(character_states.c.character_id == table.character_id)
            .values(
                state_payload=next_state.model_dump(mode="json"),
                state_revision=int(state_row["state_revision"]) + 1,
            )
        )


def test_character_castable_spells_follow_preparation_cantrips_and_remaining_slots(
    combat_routes_fixture,
) -> None:
    table, char_entry_id, _, _ = combat_routes_fixture
    _add_castable_cantrip_and_unprepared_spell(table)
    client = TestClient(app)
    url = _spell_list_url(table, char_entry_id)

    response = client.get(
        url,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert response.status_code == 200
    by_ref = {item["spell_ref"]: item for item in response.json()}

    assert "srd5.1:spell:hold-person" in by_ref
    assert 2 in by_ref["srd5.1:spell:hold-person"]["castable_slot_levels"]
    assert "srd5.1:spell:detect-magic" not in by_ref
    assert by_ref["srd5.1:spell:fire-bolt"]["castable_slot_levels"] == [0]

    _exhaust_character_slot_level(table, 2)
    exhausted_response = client.get(
        url,
        headers={"Authorization": f"Bearer {table.player_token}"},
    )
    assert exhausted_response.status_code == 200
    exhausted_by_ref = {
        item["spell_ref"]: item for item in exhausted_response.json()
    }
    hold_person_slots = exhausted_by_ref["srd5.1:spell:hold-person"][
        "castable_slot_levels"
    ]
    assert 2 not in hold_person_slots
    assert 3 in hold_person_slots


def test_monster_castable_spells_expose_aoe_save_and_single_target_attack(
    combat_routes_fixture,
) -> None:
    table, _, mage_entry_id, _ = combat_routes_fixture
    client = TestClient(app)

    response = client.get(
        _spell_list_url(table, mage_entry_id),
        headers={"Authorization": f"Bearer {table.dm_token}"},
    )
    assert response.status_code == 200
    by_ref = {item["spell_ref"]: item for item in response.json()}

    fireball = by_ref["srd5.1:spell:fireball"]
    assert fireball["targeting"] == "aoe"
    assert fireball["cast_mode"] == "save"
    assert fireball["profile_id"] is None

    fire_bolt = by_ref["srd5.1:spell:fire-bolt"]
    assert fire_bolt["targeting"] == "single"
    assert fire_bolt["cast_mode"] == "attack"
    assert fire_bolt["castable_slot_levels"] == [0]


def test_player_cannot_list_uncontrolled_monster_spells_and_get_has_no_side_effects(
    combat_routes_fixture,
) -> None:
    table, _, mage_entry_id, _ = combat_routes_fixture
    client = TestClient(app)
    spell_url = _spell_list_url(table, mage_entry_id)

    with table.engine.connect() as connection:
        before = (
            connection.scalar(select(func.count()).select_from(combat_actions)),
            connection.scalar(select(func.count()).select_from(roll_requests)),
            connection.scalar(select(func.count()).select_from(session_events)),
        )

    headers = {"Authorization": f"Bearer {table.player_token}"}
    spell_response = client.get(spell_url, headers=headers)

    # Same refusal as every other entry-scoped Combat read (_authorize_entry).
    assert spell_response.status_code == 403
    assert spell_response.json()["error"]["code"] == "table_actor_unauthorized"
    assert "Only the current Session DM" in spell_response.json()["error"]["message"]

    with table.engine.connect() as connection:
        after = (
            connection.scalar(select(func.count()).select_from(combat_actions)),
            connection.scalar(select(func.count()).select_from(roll_requests)),
            connection.scalar(select(func.count()).select_from(session_events)),
        )
    assert after == before
