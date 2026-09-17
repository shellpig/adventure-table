from __future__ import annotations

import pytest

from app.content import load_default_content_registry
from app.domain.character.schemas import (
    CharacterConcentrationState,
    CharacterDeathSaveState,
    PersistentTemporaryEffect,
    TemporaryEffectModifier,
)
from app.domain.combat.lifecycle import StartCombatInput
from app.domain.rooms.table_character_state import (
    TableCharacterStateCombatMutationError,
    TableCharacterStatePatch,
    TableCharacterStateService,
)
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_character_state import TableCharacterStatePersistence
import tests.test_p4b_combat_lifecycle as support


def _state_service(table) -> TableCharacterStateService:
    registry = load_default_content_registry()
    return TableCharacterStateService(
        TableCharacterStatePersistence(
            table.engine,
            registry,
            table.events.repository,
        ),
        ExplorationSubjectRepository(table.engine),
        table.events,
    )


def _list_events(table):
    return table.events.repository.list_after(
        room_id=table.room_id,
        campaign_id=table.campaign_id,
        session_id=table.session_id,
        after_seq=0,
        scan_limit=200,
    )


def _find_event(table, idempotency_key: str):
    return next(
        event
        for event in _list_events(table)
        if event.idempotency_key == idempotency_key
    )


def _assert_combat_mutation_refused_zero_side_effects(
    table,
    service: TableCharacterStateService,
    *,
    actor,
    patch: TableCharacterStatePatch,
) -> None:
    registry = load_default_content_registry()
    character_repo = CharacterRepository(table.engine, registry)
    state_before = character_repo.load_character(table.character_id).state
    events_before = len(_list_events(table))

    with pytest.raises(TableCharacterStateCombatMutationError):
        service.apply_patch(
            actor,
            subject_seat_id=table.player_seat_id,
            patch=patch,
        )

    events_after = len(_list_events(table))
    state_after = character_repo.load_character(table.character_id).state
    assert events_after == events_before
    assert state_after == state_before


def test_raw_hp_patch_is_normal_outside_combat_but_correction_only_during_combat() -> None:
    table = support._setup()
    try:
        service = _state_service(table)
        outside = service.apply_patch(
            table.player_actor,
            subject_seat_id=table.player_seat_id,
            patch=TableCharacterStatePatch(
                current_hp=70,
                idempotency_key="outside-combat-hp",
            ),
        )
        assert outside.state.current_hp == 70

        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="semantic-boundary-start"),
        )

        _assert_combat_mutation_refused_zero_side_effects(
            table,
            service,
            actor=table.player_actor,
            patch=TableCharacterStatePatch(
                current_hp=60,
                idempotency_key="player-raw-hp",
            ),
        )

        _assert_combat_mutation_refused_zero_side_effects(
            table,
            service,
            actor=table.dm_actor,
            patch=TableCharacterStatePatch(
                current_hp=60,
                idempotency_key="dm-hp-without-reason",
            ),
        )

        corrected = service.apply_patch(
            table.dm_actor,
            subject_seat_id=table.player_seat_id,
            patch=TableCharacterStatePatch(
                current_hp=60,
                correction_reason="Correct mistaken damage entry",
                idempotency_key="dm-hp-correction",
            ),
        )
        assert corrected.state.current_hp == 60

        correction = _find_event(table, "p3c-state:dm-hp-correction")
        assert correction.kind == "character.state.updated"
        assert correction.payload["correction"] is True
        assert correction.payload["correction_reason"] == "Correct mistaken damage entry"
        assert correction.payload["changed_fields"] == ["current_hp"]
    finally:
        table.engine.dispose()


def test_p4d_combat_state_patch_is_normal_outside_combat_but_correction_only_during_combat() -> None:
    """Test that P4-D combat-owned state fields require DM correction during active combat.

    Explicit NON-goal: a raw concentration: null correction does NOT strip linked effects
    from other combatants — that cleanup belongs to CombatConcentrationRepository.complete_check;
    the DM correction is an audited override.
    """
    table = support._setup()
    try:
        service = _state_service(table)
        registry = load_default_content_registry()
        character_repo = CharacterRepository(table.engine, registry)

        outside_effect = PersistentTemporaryEffect(
            effect_id="eff-outside-heroism",
            tag="heroism",
            duration="manual",
            modifiers=(TemporaryEffectModifier(scope="save", mode="bonus", value=1),),
        )
        outside_death_saves = CharacterDeathSaveState(successes=1, failures=1)
        outside_patch = TableCharacterStatePatch(
            exhaustion_level=1,
            death_saves=outside_death_saves,
            temporary_effects=[outside_effect],
            concentration=None,
            idempotency_key="outside-combat-p4d-state",
        )

        outside = service.apply_patch(
            table.player_actor,
            subject_seat_id=table.player_seat_id,
            patch=outside_patch,
        )
        assert outside.state.exhaustion_level == 1
        assert outside.state.death_saves == outside_death_saves
        assert outside.state.temporary_effects == [outside_effect]
        assert outside.state.concentration is None

        outside_event = _find_event(table, "p3c-state:outside-combat-p4d-state")
        assert outside_event.kind == "character.state.updated"
        assert outside_event.payload["changed_fields"] == [
            "concentration",
            "death_saves",
            "exhaustion_level",
            "temporary_effects",
        ]
        assert "correction" not in outside_event.payload

        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="semantic-p4d-boundary-start"),
        )

        # Active combat: Player patch refused with zero side effects
        player_combat_patch = TableCharacterStatePatch(
            exhaustion_level=1,
            death_saves=outside_death_saves,
            temporary_effects=[outside_effect],
            concentration=None,
            idempotency_key="player-p4d-combat-attempt",
        )
        _assert_combat_mutation_refused_zero_side_effects(
            table,
            service,
            actor=table.player_actor,
            patch=player_combat_patch,
        )

        # Active combat: DM without correction_reason refused with zero side effects
        dm_no_reason_patch = TableCharacterStatePatch(
            exhaustion_level=2,
            death_saves=CharacterDeathSaveState(successes=2, failures=0),
            idempotency_key="dm-p4d-without-reason",
        )
        _assert_combat_mutation_refused_zero_side_effects(
            table,
            service,
            actor=table.dm_actor,
            patch=dm_no_reason_patch,
        )

        # Active combat: DM with correction_reason succeeds
        dm_concentration = CharacterConcentrationState(
            source_ref="srd5.1:spell:bless",
            effect_ids=(),
        )
        dm_effect = PersistentTemporaryEffect(
            effect_id="eff-dm-shield",
            tag="shield-of-faith",
            duration="manual",
            modifiers=(TemporaryEffectModifier(scope="ac", mode="bonus", value=2),),
        )
        dm_death_saves = CharacterDeathSaveState(successes=2, failures=0)
        dm_correction_patch = TableCharacterStatePatch(
            concentration=dm_concentration,
            exhaustion_level=2,
            death_saves=dm_death_saves,
            temporary_effects=[dm_effect],
            correction_reason="Audited correction of combat-owned status effects",
            idempotency_key="dm-p4d-correction",
        )

        corrected = service.apply_patch(
            table.dm_actor,
            subject_seat_id=table.player_seat_id,
            patch=dm_correction_patch,
        )

        persisted = character_repo.load_character(table.character_id)
        assert persisted.state.concentration == dm_concentration
        assert persisted.state.exhaustion_level == 2
        assert persisted.state.death_saves == dm_death_saves
        assert persisted.state.temporary_effects == [dm_effect]
        assert corrected.state == persisted.state

        correction_event = _find_event(table, "p3c-state:dm-p4d-correction")
        assert correction_event.kind == "character.state.updated"
        assert correction_event.payload["correction"] is True
        assert correction_event.payload["correction_reason"] == "Audited correction of combat-owned status effects"
        assert correction_event.payload["changed_fields"] == [
            "concentration",
            "death_saves",
            "exhaustion_level",
            "temporary_effects",
        ]
    finally:
        table.engine.dispose()
