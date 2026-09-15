from __future__ import annotations

import pytest

from app.content import load_default_content_registry
from app.domain.combat.lifecycle import StartCombatInput
from app.domain.rooms.table_character_state import (
    TableCharacterStateCombatMutationError,
    TableCharacterStatePatch,
    TableCharacterStateService,
)
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

        with pytest.raises(TableCharacterStateCombatMutationError):
            service.apply_patch(
                table.player_actor,
                subject_seat_id=table.player_seat_id,
                patch=TableCharacterStatePatch(
                    current_hp=60,
                    idempotency_key="player-raw-hp",
                ),
            )

        with pytest.raises(TableCharacterStateCombatMutationError):
            service.apply_patch(
                table.dm_actor,
                subject_seat_id=table.player_seat_id,
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

        events = table.events.repository.list_after(
            room_id=table.room_id,
            campaign_id=table.campaign_id,
            session_id=table.session_id,
            after_seq=0,
            scan_limit=200,
        )
        correction = next(
            event
            for event in events
            if event.idempotency_key == "p3c-state:dm-hp-correction"
        )
        assert correction.kind == "character.state.updated"
        assert correction.payload["correction"] is True
        assert correction.payload["correction_reason"] == "Correct mistaken damage entry"
        assert correction.payload["changed_fields"] == ["current_hp"]
    finally:
        table.engine.dispose()
