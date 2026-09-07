from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import os
from pathlib import Path
from threading import Barrier
from uuid import UUID, uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import create_engine, func, insert, select, text, update
from sqlalchemy.engine import Engine

from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import CharacterAlreadyInActiveSessionError, SessionService
from app.persistence.characters import characters
from app.persistence.rooms.session_live import LateJoinPersistenceError, SessionLiveRepository
from app.persistence.rooms.sessions import (
    CharacterAlreadyLeasedPersistenceError,
    ParticipantSeed,
    SessionRepository,
)
from app.persistence.rooms.tables import (
    active_character_session_leases,
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
    session_participants,
    sessions,
)


POSTGRES_URL = os.environ.get("P2_POSTGRES_URL")
pytestmark = pytest.mark.skipif(
    not POSTGRES_URL,
    reason="P2_POSTGRES_URL is only supplied by the P2 Non-E2E PostgreSQL job",
)
SERVER_ROOT = Path(__file__).resolve().parents[1]


def _alembic_config() -> Config:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    assert POSTGRES_URL is not None
    config.set_main_option("sqlalchemy.url", POSTGRES_URL)
    return config


@pytest.fixture()
def postgres_engine() -> Engine:
    assert POSTGRES_URL is not None
    engine = create_engine(POSTGRES_URL, pool_pre_ping=True)
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    command.upgrade(_alembic_config(), "heads")
    try:
        yield engine
    finally:
        engine.dispose()


def _seed_concurrent_sessions(engine: Engine):
    room_id = uuid4()
    dm_access_id = uuid4()
    character_id = uuid4()
    campaign_ids = (uuid4(), uuid4())
    dm_seat_ids = (uuid4(), uuid4())
    player_seat_ids = (uuid4(), uuid4())
    now = datetime.now(timezone.utc)

    with engine.begin() as connection:
        connection.execute(
            insert(rooms).values(
                id=room_id,
                code="P2ELEASE01",
                name="P2-E concurrent lease",
                password_salt=b"s" * 32,
                password_hash=b"p" * 64,
                owner_key_hash=b"o" * 32,
                dm_key_hash=b"d" * 32,
                active_campaign_id=None,
                created_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(room_access_sessions).values(
                id=dm_access_id,
                room_id=room_id,
                authority="dm",
                token_hash=b"t" * 32,
                display_name="Concurrent DM",
                created_at=now,
                last_seen_at=now,
                revoked_at=None,
            )
        )
        connection.execute(
            insert(characters).values(
                id=character_id,
                name="Mira",
                ruleset="dnd5e-2014",
                current_version_id=None,
                archived_at=None,
            )
        )
        connection.execute(
            insert(room_characters).values(
                room_id=room_id,
                character_id=character_id,
                created_at=now,
            )
        )
        for index, campaign_id in enumerate(campaign_ids):
            connection.execute(
                insert(campaigns).values(
                    id=campaign_id,
                    room_id=room_id,
                    name=f"Campaign {index + 1}",
                    ruleset="dnd5e-2014",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(campaign_roster_entries).values(
                    campaign_id=campaign_id,
                    character_id=character_id,
                    status="active",
                    added_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(campaign_seats),
                [
                    {
                        "id": dm_seat_ids[index],
                        "campaign_id": campaign_id,
                        "role": "dm",
                        "label": f"DM {index + 1}",
                        "controller_kind": "human",
                        "controller_access_session_id": dm_access_id,
                        "selected_character_id": None,
                        "archived_at": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": player_seat_ids[index],
                        "campaign_id": campaign_id,
                        "role": "player",
                        "label": f"Player {index + 1}",
                        "controller_kind": "none",
                        "controller_access_session_id": None,
                        "selected_character_id": character_id,
                        "archived_at": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                ],
            )

    return room_id, dm_access_id, character_id, campaign_ids, dm_seat_ids, player_seat_ids


def _participant_seeds(
    *,
    dm_access_id: UUID,
    character_id: UUID,
    dm_seat_id: UUID,
    player_seat_id: UUID,
) -> tuple[ParticipantSeed, ParticipantSeed]:
    return (
        ParticipantSeed(
            seat_id=dm_seat_id,
            role_snapshot="dm",
            controller_kind_at_join="human",
            controller_access_session_id_at_join=dm_access_id,
            active_character_id=None,
        ),
        ParticipantSeed(
            seat_id=player_seat_id,
            role_snapshot="player",
            controller_kind_at_join="none",
            controller_access_session_id_at_join=None,
            active_character_id=character_id,
        ),
    )


def test_concurrent_session_lease_collision_has_one_atomic_winner(
    postgres_engine: Engine,
) -> None:
    (
        _room_id,
        dm_access_id,
        character_id,
        campaign_ids,
        dm_seat_ids,
        player_seat_ids,
    ) = _seed_concurrent_sessions(postgres_engine)
    start = Barrier(2)

    def attempt(index: int) -> tuple[str, UUID | None]:
        repository = SessionRepository(postgres_engine)
        start.wait(timeout=10)
        try:
            stored = repository.create_with_participants(
                campaign_id=campaign_ids[index],
                dm_seat_id=dm_seat_ids[index],
                dm_controller_kind="human",
                dm_controller_access_session_id=dm_access_id,
                participants=_participant_seeds(
                    dm_access_id=dm_access_id,
                    character_id=character_id,
                    dm_seat_id=dm_seat_ids[index],
                    player_seat_id=player_seat_ids[index],
                ),
            )
            return ("ok", stored.id)
        except CharacterAlreadyLeasedPersistenceError:
            return ("conflict", None)

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = [
            future.result(timeout=20)
            for future in (
                executor.submit(attempt, 0),
                executor.submit(attempt, 1),
            )
        ]

    assert sorted(outcome for outcome, _session_id in outcomes) == ["conflict", "ok"]
    winner_id = next(session_id for outcome, session_id in outcomes if outcome == "ok")
    assert winner_id is not None

    with postgres_engine.connect() as connection:
        persisted_sessions = connection.execute(
            select(sessions.c.id, sessions.c.campaign_id).where(
                sessions.c.campaign_id.in_(campaign_ids)
            )
        ).all()
        persisted_participants = connection.scalar(
            select(func.count()).select_from(session_participants).where(
                session_participants.c.session_id.in_([row.id for row in persisted_sessions])
            )
        )
        leases = connection.execute(
            select(active_character_session_leases).where(
                active_character_session_leases.c.character_id == character_id
            )
        ).mappings().all()

    assert len(persisted_sessions) == 1
    assert persisted_sessions[0].id == winner_id
    assert persisted_participants == 2
    assert len(leases) == 1
    assert leases[0]["session_id"] == winner_id


def test_cross_campaign_start_maps_existing_global_lease_to_stable_domain_error(
    postgres_engine: Engine,
) -> None:
    (
        room_id,
        dm_access_id,
        character_id,
        campaign_ids,
        dm_seat_ids,
        player_seat_ids,
    ) = _seed_concurrent_sessions(postgres_engine)
    repository = SessionRepository(postgres_engine)
    first = repository.create_with_participants(
        campaign_id=campaign_ids[0],
        dm_seat_id=dm_seat_ids[0],
        dm_controller_kind="human",
        dm_controller_access_session_id=dm_access_id,
        participants=_participant_seeds(
            dm_access_id=dm_access_id,
            character_id=character_id,
            dm_seat_id=dm_seat_ids[0],
            player_seat_id=player_seat_ids[0],
        ),
    )
    with postgres_engine.begin() as connection:
        connection.execute(
            update(rooms)
            .where(rooms.c.id == room_id)
            .values(active_campaign_id=campaign_ids[1])
        )

    service = SessionService(repository, SessionLiveRepository(postgres_engine))
    context = RoomAccessContext(
        room_id=room_id,
        access_session_id=dm_access_id,
        authority=RoomAccessAuthority.DM,
        display_name="Concurrent DM",
    )
    with pytest.raises(CharacterAlreadyInActiveSessionError):
        service.start_session(room_id, campaign_ids[1], context)

    assert repository.lease_for_character(character_id).session_id == first.id
    with postgres_engine.connect() as connection:
        assert connection.scalar(
            select(func.count()).select_from(sessions).where(
                sessions.c.campaign_id.in_(campaign_ids)
            )
        ) == 1
        assert connection.scalar(
            select(func.count()).select_from(session_participants).where(
                session_participants.c.session_id == first.id
            )
        ) == 2


def test_end_and_late_join_serialize_without_partial_lease(
    postgres_engine: Engine,
) -> None:
    (
        room_id,
        dm_access_id,
        character_id,
        campaign_ids,
        dm_seat_ids,
        player_seat_ids,
    ) = _seed_concurrent_sessions(postgres_engine)
    campaign_id = campaign_ids[0]
    repository = SessionRepository(postgres_engine)
    started = repository.create_with_participants(
        campaign_id=campaign_id,
        dm_seat_id=dm_seat_ids[0],
        dm_controller_kind="human",
        dm_controller_access_session_id=dm_access_id,
        participants=_participant_seeds(
            dm_access_id=dm_access_id,
            character_id=character_id,
            dm_seat_id=dm_seat_ids[0],
            player_seat_id=player_seat_ids[0],
        ),
    )

    late_character_id = uuid4()
    late_seat_id = uuid4()
    now = datetime.now(timezone.utc)
    with postgres_engine.begin() as connection:
        connection.execute(
            insert(characters).values(
                id=late_character_id,
                name="Luna",
                ruleset="dnd5e-2014",
                current_version_id=None,
                archived_at=None,
            )
        )
        connection.execute(
            insert(room_characters).values(
                room_id=room_id,
                character_id=late_character_id,
                created_at=now,
            )
        )
        connection.execute(
            insert(campaign_roster_entries).values(
                campaign_id=campaign_id,
                character_id=late_character_id,
                status="active",
                added_at=now,
                updated_at=now,
            )
        )
        connection.execute(
            insert(campaign_seats).values(
                id=late_seat_id,
                campaign_id=campaign_id,
                role="player",
                label="Late Luna",
                controller_kind="none",
                controller_access_session_id=None,
                selected_character_id=late_character_id,
                archived_at=None,
                created_at=now,
                updated_at=now,
            )
        )

    start = Barrier(2)

    def end_attempt() -> str:
        start.wait(timeout=10)
        finalized = SessionRepository(postgres_engine).finalize(started.id, status="ended")
        assert finalized is not None
        return "ended"

    def join_attempt() -> str:
        start.wait(timeout=10)
        try:
            SessionLiveRepository(postgres_engine).late_join_from_lobby(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=started.id,
                caller_access_session_id=dm_access_id,
                seat_id=late_seat_id,
            )
        except LateJoinPersistenceError:
            return "rejected"
        return "joined"

    with ThreadPoolExecutor(max_workers=2) as executor:
        end_future = executor.submit(end_attempt)
        join_future = executor.submit(join_attempt)
        outcomes = {end_future.result(timeout=20), join_future.result(timeout=20)}

    assert "ended" in outcomes
    assert outcomes & {"joined", "rejected"}
    persisted = repository.get(started.id)
    assert persisted is not None
    assert persisted.status == "ended"
    assert repository.lease_for_character(character_id) is None
    assert repository.lease_for_character(late_character_id) is None

    participants = repository.list_participants(started.id)
    assert len(participants) in {2, 3}
    if any(participant.active_character_id == late_character_id for participant in participants):
        assert len(participants) == 3
    else:
        assert len(participants) == 2
