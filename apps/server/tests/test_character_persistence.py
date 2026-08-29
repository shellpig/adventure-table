from __future__ import annotations

from sqlalchemy import create_engine, func, select

from app.content.registry import load_default_content_registry
from app.db import metadata
from app.domain.character.fixture import (
    P0_FIXTURE_NAME,
    build_p0_fighter_wizard_fixture,
    build_p0_fighter_wizard_state,
)
from app.domain.character.schemas import (
    CharacterState,
    ConditionState,
    InventoryEntry,
    ResourceCounter,
)
from app.persistence.characters import CharacterRepository, character_versions


def test_p0_fixture_save_reload_and_state_isolation(tmp_path) -> None:
    database_path = tmp_path / "p0c.sqlite3"
    database_url = f"sqlite+pysqlite:///{database_path}"
    registry = load_default_content_registry()

    engine = create_engine(database_url)
    metadata.create_all(engine)
    repository = CharacterRepository(engine, registry)

    build = build_p0_fighter_wizard_fixture()
    state = build_p0_fighter_wizard_state()
    created = repository.create_character(
        name=P0_FIXTURE_NAME,
        build=build,
        state=state,
    )

    assert created.version_no == 1
    assert created.build == build
    assert created.state == state
    assert created.build.character_level == 10
    assert created.build.class_progression[:5] == ("srd5.1:class:fighter",) * 5
    assert created.build.class_progression[5:] == ("srd5.1:class:wizard",) * 5
    assert created.state.hit_dice_state == {"d10": 5, "d6": 5}

    version_id_before = created.current_version_id
    build_payload_before = created.build.model_dump(mode="json")

    mutated_state = CharacterState.model_validate(created.state.model_dump(mode="json"))
    mutated_state.current_hp = 61
    mutated_state.temporary_hp = 4
    mutated_state.prepared_spell_entry_ids = [
        "wizard:magic-missile",
        "wizard:fireball",
    ]
    mutated_state.conditions = [
        ConditionState(
            condition_ref="srd5.1:condition:poisoned",
            note="P0-C persistence regression",
        )
    ]
    mutated_state.spell_slots[1] = ResourceCounter(used=2, remaining=2)
    mutated_state.hit_dice_state["d10"] = 4

    updated_inventory = []
    for entry in mutated_state.inventory_state:
        if entry.entry_id == "inventory:longsword":
            continue
        if entry.entry_id == "inventory:shield":
            entry = entry.model_copy(update={"equipped": False})
        if entry.entry_id == "inventory:healing-potion":
            entry = entry.model_copy(update={"quantity": 1})
        updated_inventory.append(entry)
    updated_inventory.append(
        InventoryEntry(
            entry_id="inventory:dagger",
            item_ref="srd5.1:equipment:dagger",
            quantity=1,
            equipped=False,
        )
    )
    mutated_state.inventory_state = updated_inventory

    saved = repository.save_state(created.id, mutated_state)

    assert saved.current_version_id == version_id_before
    assert saved.version_no == 1
    assert saved.build.model_dump(mode="json") == build_payload_before
    assert saved.state.current_hp == 61
    assert saved.state.temporary_hp == 4
    assert saved.state.hit_dice_state == {"d10": 4, "d6": 5}

    with engine.connect() as connection:
        version_count = connection.scalar(select(func.count()).select_from(character_versions))
    assert version_count == 1

    engine.dispose()

    fresh_engine = create_engine(database_url)
    fresh_repository = CharacterRepository(fresh_engine, registry)
    reloaded = fresh_repository.load_character(created.id)

    assert reloaded.current_version_id == version_id_before
    assert reloaded.build.model_dump(mode="json") == build_payload_before
    assert reloaded.state == mutated_state

    live_inventory = {entry.entry_id: entry for entry in reloaded.state.inventory_state}
    assert "inventory:longsword" not in live_inventory
    assert live_inventory["inventory:shield"].equipped is False
    assert live_inventory["inventory:healing-potion"].quantity == 1
    assert live_inventory["inventory:dagger"].item_ref == "srd5.1:equipment:dagger"

    starting_refs = {entry.item_ref for entry in reloaded.build.starting_equipment}
    assert "srd5.1:equipment:longsword" in starting_refs
    assert "srd5.1:equipment:longsword" not in {
        entry.item_ref for entry in reloaded.state.inventory_state
    }

    fresh_engine.dispose()
