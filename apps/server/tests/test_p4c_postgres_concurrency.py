from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import os
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, select, text

from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.semantic_hp import CombatResolutionService, SemanticDamageInput
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.persistence.characters import character_states
from app.persistence.combat.resolution import CombatResolutionRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events, session_table_runtime
import tests.test_p4b_combat_lifecycle as support


POSTGRES_URL = os.environ.get("P4_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P4_POSTGRES_URL is only supplied by the P4 PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    config.attributes["target_database_url"] = POSTGRES_URL
    return config


def _reset() -> None:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL)
    try:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA public CASCADE"))
            connection.execute(text("CREATE SCHEMA public"))
    finally:
        engine.dispose()
    command.upgrade(_config(), "heads")


def _running_table(monkeypatch):
    _reset()
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    monkeypatch.setattr(support, "create_engine", lambda *_args, **_kwargs: engine)
    table = support._setup()
    combat = table.combat.start_quick_combat(
        table.dm_actor,
        StartCombatInput(idempotency_key="p4c-concurrency-start"),
    )
    enemy = support._quick_enemy(table, "Target")
    combat = table.combat.add_monster(
        table.dm_actor,
        AddMonsterInput(
            monster_instance_id=enemy.id,
            idempotency_key="p4c-concurrency-enemy",
        ),
    )
    requested = table.initiative.request_initiative(
        table.dm_actor,
        RequestInitiativeInput(idempotency_key="p4c-concurrency-init"),
    )
    for request in requested.requests:
        actor = table.player_actor if request.target_seat_id is not None else table.dm_actor
        raw = 20 if request.target_seat_id is not None else 1
        table.initiative.complete_initiative(
            actor,
            FormalRollInput(
                roll_request_id=request.id,
                source=FormalRollSource.PHYSICAL,
                raw_dice=(raw,),
                idempotency_key=f"p4c-concurrency-init-{request.id}",
            ),
        )
    order = table.initiative.suggested_order(table.dm_actor)
    table.initiative.finalize_initiative(
        table.dm_actor,
        FinalizeInitiativeInput(
            ordered_entry_ids=order,
            idempotency_key="p4c-concurrency-finalize",
        ),
    )
    character_entry = next(
        entry for entry in combat.entries if entry.character_id == table.character_id
    )
    resolution = CombatResolutionService(
        CombatResolutionRepository(engine, table.events.repository),
        table.combat.repository,
        table.combat,
        table.events,
    )
    return engine, table, character_entry.id, resolution


class _InjectedFailureEventRepository(TableEventRepository):
    def __init__(self, engine, *, after_projection: bool) -> None:
        super().__init__(engine)
        self.after_projection = after_projection

    def append(self, *args, **kwargs):
        original_projection = kwargs.get("transaction_projection")
        assert original_projection is not None

        def injected_projection(connection, event_id, seq):
            if not self.after_projection:
                raise RuntimeError("injected failure after event insert before HP projection")
            original_projection(connection, event_id, seq)
            raise RuntimeError("injected failure after HP projection before commit")

        kwargs["transaction_projection"] = injected_projection
        return super().append(*args, **kwargs)


def _hp(engine, character_id) -> int:
    with engine.connect() as connection:
        payload = connection.execute(
            select(character_states.c.state_payload).where(
                character_states.c.character_id == character_id
            )
        ).scalar_one()
    return int(payload["current_hp"])


def test_concurrent_duplicate_semantic_damage_changes_hp_once(monkeypatch) -> None:
    engine, table, target_entry_id, resolution = _running_table(monkeypatch)
    try:
        before_hp = _hp(engine, table.character_id)
        request = SemanticDamageInput(
            target_entry_id=target_entry_id,
            amount=7,
            idempotency_key="duplicate-damage",
        )

        def apply_once():
            return resolution.apply_damage(table.player_actor, request)

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _index: apply_once(), range(2)))

        assert results[0].event_id == results[1].event_id
        assert _hp(engine, table.character_id) == max(0, before_hp - 7)
        with engine.connect() as connection:
            event_count = connection.scalar(
                select(func.count()).select_from(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.idempotency_key == "p4c-damage:duplicate-damage",
                )
            )
        assert event_count == 1
    finally:
        engine.dispose()


@pytest.mark.parametrize("after_projection", [False, True])
def test_semantic_damage_transaction_failure_leaves_no_half_state(monkeypatch, after_projection: bool) -> None:
    engine, table, target_entry_id, _resolution = _running_table(monkeypatch)
    try:
        before_hp = _hp(engine, table.character_id)
        with engine.connect() as connection:
            before_runtime = connection.execute(
                select(
                    session_table_runtime.c.revision,
                    session_table_runtime.c.last_event_seq,
                ).where(session_table_runtime.c.session_id == table.session_id)
            ).one()

        failing_events = _InjectedFailureEventRepository(
            engine,
            after_projection=after_projection,
        )
        resolution = CombatResolutionService(
            CombatResolutionRepository(engine, failing_events),
            table.combat.repository,
            table.combat,
            table.events,
        )
        key = f"rollback-{'after' if after_projection else 'before'}-projection"
        with pytest.raises(RuntimeError, match="injected failure"):
            resolution.apply_damage(
                table.player_actor,
                SemanticDamageInput(
                    target_entry_id=target_entry_id,
                    amount=7,
                    idempotency_key=key,
                ),
            )

        assert _hp(engine, table.character_id) == before_hp
        with engine.connect() as connection:
            event_count = connection.scalar(
                select(func.count()).select_from(session_events).where(
                    session_events.c.session_id == table.session_id,
                    session_events.c.idempotency_key == f"p4c-damage:{key}",
                )
            )
            after_runtime = connection.execute(
                select(
                    session_table_runtime.c.revision,
                    session_table_runtime.c.last_event_seq,
                ).where(session_table_runtime.c.session_id == table.session_id)
            ).one()
        assert event_count == 0
        assert after_runtime == before_runtime
    finally:
        engine.dispose()
