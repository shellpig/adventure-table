from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from uuid import UUID, uuid4

import pytest
from sqlalchemy import Engine, create_engine, func, insert, select, update

from app.db import metadata
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import (
    AIControllerService,
    AIControllerUnauthorizedError,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import (
    DMControllerMismatchError,
    SessionService,
    SessionSnapshot,
    SessionStatus,
)
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.characters import character_states, characters
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository, session_events
from app.persistence.rooms.tables import (
    active_character_session_leases,
    ai_controller_grants,
    campaign_roster_entries,
    campaign_seats,
    campaigns,
    room_access_sessions,
    room_characters,
    rooms,
    session_participants,
    sessions,
)


@dataclass(frozen=True)
class AIDMSessionFixture:
    engine: Engine
    room_id: UUID
    campaign_id: UUID
    dm_seat_id: UUID
    owner_access_id: UUID
    dm_access_id: UUID
    member_access_id: UUID
    player_seat_id: UUID
    player_character_id: UUID
    participant_id: UUID
    dm_token: str
    dm_grant_id: UUID
    dm_generation: int
    player_token_plaintext: str
    player_grant_id: UUID
    session: SessionSnapshot
    session_service: SessionService
    controller_service: AIControllerService
    event_service: TableEventService
    session_repository: SessionRepository


@dataclass(frozen=True)
class HumanDMSessionFixture:
    engine: Engine
    room_id: UUID
    campaign_id: UUID
    dm_seat_id: UUID
    owner_access_id: UUID
    dm_access_id: UUID
    session: SessionSnapshot
    session_service: SessionService
    session_repository: SessionRepository


def _seed_room_and_campaign(connection, *, room_id, campaign_id, code: str, name: str, now) -> None:
    connection.execute(
        insert(rooms).values(
            id=room_id,
            code=code,
            name=name,
            password_salt=b"s" * 32,
            password_hash=b"h" * 64,
            owner_key_hash=b"o" * 32,
            dm_key_hash=b"d" * 32,
            active_campaign_id=None,
            created_at=now,
            updated_at=now,
        )
    )
    connection.execute(
        insert(campaigns).values(
            id=campaign_id,
            room_id=room_id,
            name="Campaign",
            ruleset="dnd5e-2014",
            status="active",
        )
    )
    connection.execute(
        update(rooms).where(rooms.c.id == room_id).values(active_campaign_id=campaign_id)
    )


def _insert_access_session(
    connection, *, access_id, room_id, authority: str, display_name: str, token_hash: bytes, now
) -> None:
    connection.execute(
        insert(room_access_sessions).values(
            id=access_id,
            room_id=room_id,
            authority=authority,
            token_hash=token_hash,
            display_name=display_name,
            created_at=now,
            last_seen_at=now,
            revoked_at=None,
        )
    )


def _create_ai_dm_fixture() -> AIDMSessionFixture:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    event_service = TableEventService(TableEventRepository(engine))
    grant_repository = AIControllerGrantRepository(engine)
    controller_service = AIControllerService(grant_repository, event_service)
    session_repository = SessionRepository(engine)
    session_service = SessionService(
        session_repository,
        SessionLiveRepository(engine),
        event_service,
    )
    now = datetime.now(timezone.utc)
    room_id, campaign_id, dm_seat_id = uuid4(), uuid4(), uuid4()
    owner_access_id, dm_access_id, member_access_id = uuid4(), uuid4(), uuid4()

    with engine.begin() as connection:
        _seed_room_and_campaign(
            connection,
            room_id=room_id,
            campaign_id=campaign_id,
            code="M05AID",
            name="AI DM Session Room",
            now=now,
        )
        connection.execute(
            insert(campaign_seats).values(
                id=dm_seat_id,
                campaign_id=campaign_id,
                role="dm",
                label="AI DM",
                controller_kind="none",
                controller_access_session_id=None,
                ai_controller_grant_id=None,
                controller_epoch=0,
                selected_character_id=None,
                archived_at=None,
            )
        )
        for access_id, authority, display_name, token_hash in [
            (owner_access_id, "owner", "Owner", b"o" * 32),
            (dm_access_id, "dm", "DM Keyholder", b"d" * 32),
            (member_access_id, "member", "Member", b"m" * 32),
        ]:
            _insert_access_session(
                connection,
                access_id=access_id,
                room_id=room_id,
                authority=authority,
                display_name=display_name,
                token_hash=token_hash,
                now=now,
            )

    dm_issued = controller_service.configure_pre_session_ai_dm(
        room_id=room_id,
        campaign_id=campaign_id,
        seat_id=dm_seat_id,
    )
    started = session_service.start_session_as_ai_dm(
        room_id,
        campaign_id,
        grant_id=dm_issued.grant_id,
        generation=dm_issued.generation,
    )

    player_seat_id = uuid4()
    player_character_id = uuid4()
    participant_id = uuid4()
    player_token = mint_ai_controller_token()

    with engine.begin() as connection:
        connection.execute(
            insert(characters).values(
                id=player_character_id,
                name="AI Player Character",
                ruleset="dnd5e-2014",
                current_version_id=None,
                archived_at=None,
            )
        )
        connection.execute(
            insert(room_characters).values(
                room_id=room_id,
                character_id=player_character_id,
            )
        )
        connection.execute(
            insert(campaign_roster_entries).values(
                campaign_id=campaign_id,
                character_id=player_character_id,
                status="active",
            )
        )
        connection.execute(
            insert(character_states).values(
                character_id=player_character_id,
                state_payload={"current_hp": 12, "temp_hp": 3},
                state_revision=1,
            )
        )
        connection.execute(
            insert(campaign_seats).values(
                id=player_seat_id,
                campaign_id=campaign_id,
                role="player",
                label="AI Player",
                controller_kind="none",
                controller_access_session_id=None,
                ai_controller_grant_id=None,
                controller_epoch=0,
                selected_character_id=player_character_id,
                archived_at=None,
            )
        )
        connection.execute(
            insert(session_participants).values(
                id=participant_id,
                session_id=started.id,
                seat_id=player_seat_id,
                role_snapshot="player",
                controller_kind_at_join="none",
                controller_access_session_id_at_join=None,
                controller_ai_grant_id_at_join=None,
                controller_generation_at_join=None,
                active_character_id=player_character_id,
                joined_at=now,
                left_at=None,
            )
        )
        connection.execute(
            insert(active_character_session_leases).values(
                character_id=player_character_id,
                session_id=started.id,
                participant_id=participant_id,
            )
        )
        connection.execute(
            insert(ai_controller_grants).values(
                id=player_token.grant_id,
                room_id=room_id,
                campaign_id=campaign_id,
                seat_id=player_seat_id,
                role="player",
                session_id=started.id,
                secret_hash=player_token.secret_hash,
                secret_prefix=player_token.display_hint,
                generation=1,
                status="active",
                pre_session_expires_at=None,
                handoff_return_access_session_id=owner_access_id,
                temporary_instruction="Protect the party",
                created_at=now,
                bound_at=now,
                revoked_at=None,
                last_seen_at=None,
            )
        )
        connection.execute(
            update(campaign_seats)
            .where(campaign_seats.c.id == player_seat_id)
            .values(
                controller_kind="ai",
                controller_access_session_id=None,
                ai_controller_grant_id=player_token.grant_id,
                controller_epoch=1,
                updated_at=now,
            )
        )

    return AIDMSessionFixture(
        engine=engine,
        room_id=room_id,
        campaign_id=campaign_id,
        dm_seat_id=dm_seat_id,
        owner_access_id=owner_access_id,
        dm_access_id=dm_access_id,
        member_access_id=member_access_id,
        player_seat_id=player_seat_id,
        player_character_id=player_character_id,
        participant_id=participant_id,
        dm_token=dm_issued.token,
        dm_grant_id=dm_issued.grant_id,
        dm_generation=dm_issued.generation,
        player_token_plaintext=player_token.plaintext,
        player_grant_id=player_token.grant_id,
        session=started,
        session_service=session_service,
        controller_service=controller_service,
        event_service=event_service,
        session_repository=session_repository,
    )


def _create_human_dm_fixture(*, owner_is_dm: bool = False) -> HumanDMSessionFixture:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)
    event_service = TableEventService(TableEventRepository(engine))
    session_repository = SessionRepository(engine)
    session_service = SessionService(
        session_repository,
        SessionLiveRepository(engine),
        event_service,
    )
    now = datetime.now(timezone.utc)
    room_id, campaign_id, dm_seat_id = uuid4(), uuid4(), uuid4()
    owner_access_id, dm_access_id = uuid4(), uuid4()

    dm_controller_access_id = owner_access_id if owner_is_dm else dm_access_id
    dm_controller_authority = "owner" if owner_is_dm else "dm"

    with engine.begin() as connection:
        _seed_room_and_campaign(
            connection,
            room_id=room_id,
            campaign_id=campaign_id,
            code="M05HDM",
            name="Human DM Session Room",
            now=now,
        )
        for access_id, authority, display_name, token_hash in [
            (owner_access_id, "owner", "Owner", b"o" * 32),
            (dm_access_id, "dm", "DM", b"d" * 32),
        ]:
            _insert_access_session(
                connection,
                access_id=access_id,
                room_id=room_id,
                authority=authority,
                display_name=display_name,
                token_hash=token_hash,
                now=now,
            )
        connection.execute(
            insert(campaign_seats).values(
                id=dm_seat_id,
                campaign_id=campaign_id,
                role="dm",
                label="Human DM",
                controller_kind="human",
                controller_access_session_id=dm_controller_access_id,
                ai_controller_grant_id=None,
                controller_epoch=1,
                selected_character_id=None,
                archived_at=None,
            )
        )

    started = session_service.start_session(
        room_id,
        campaign_id,
        RoomAccessContext(
            room_id=room_id,
            access_session_id=dm_controller_access_id,
            authority=RoomAccessAuthority(dm_controller_authority),
        ),
    )

    return HumanDMSessionFixture(
        engine=engine,
        room_id=room_id,
        campaign_id=campaign_id,
        dm_seat_id=dm_seat_id,
        owner_access_id=owner_access_id,
        dm_access_id=dm_access_id,
        session=started,
        session_service=session_service,
        session_repository=session_repository,
    )


def test_owner_end_ai_dm_session_finalizes_and_revokes_atomically() -> None:
    fix = _create_ai_dm_fixture()
    try:
        owner_context = RoomAccessContext(
            room_id=fix.room_id,
            access_session_id=fix.owner_access_id,
            authority=RoomAccessAuthority.OWNER,
        )
        ended = fix.session_service.end_session(
            fix.room_id,
            fix.campaign_id,
            fix.session.id,
            owner_context,
        )
        assert ended.status == SessionStatus.ENDED
        assert ended.ended_at is not None

        with fix.engine.connect() as connection:
            grant_rows = connection.execute(
                select(
                    ai_controller_grants.c.id,
                    ai_controller_grants.c.status,
                    ai_controller_grants.c.temporary_instruction,
                ).where(ai_controller_grants.c.session_id == fix.session.id)
            ).mappings().all()
            assert len(grant_rows) == 2
            assert all(row["status"] == "revoked" for row in grant_rows)
            assert all(row["temporary_instruction"] is None for row in grant_rows)

            seat_rows = connection.execute(
                select(
                    campaign_seats.c.id,
                    campaign_seats.c.controller_kind,
                    campaign_seats.c.ai_controller_grant_id,
                    campaign_seats.c.controller_epoch,
                ).where(campaign_seats.c.id.in_([fix.dm_seat_id, fix.player_seat_id]))
            ).mappings().all()
            seats_by_id = {row["id"]: row for row in seat_rows}

            dm_seat = seats_by_id[fix.dm_seat_id]
            assert dm_seat["controller_kind"] == "none"
            assert dm_seat["ai_controller_grant_id"] is None
            assert dm_seat["controller_epoch"] == fix.dm_generation + 1

            player_seat = seats_by_id[fix.player_seat_id]
            assert player_seat["controller_kind"] == "none"
            assert player_seat["ai_controller_grant_id"] is None
            assert player_seat["controller_epoch"] == 2

            lease_count = connection.scalar(
                select(func.count()).select_from(active_character_session_leases).where(
                    active_character_session_leases.c.session_id == fix.session.id
                )
            )
            assert lease_count == 0

            events = connection.execute(
                select(session_events).where(session_events.c.session_id == fix.session.id).order_by(session_events.c.seq)
            ).mappings().all()
            last_event = events[-1]
            assert last_event["kind"] == "session.ended"
            assert last_event["execution_mode"] == "system"
            assert last_event["acting_seat_id"] is None
            assert last_event["payload"] == {
                "status": "ended",
                "owner_access_session_id": str(fix.owner_access_id),
            }
    finally:
        fix.engine.dispose()


def test_owner_end_ai_dm_via_service_matches_owner_abandon_side_effects() -> None:
    fix_end = _create_ai_dm_fixture()
    fix_abandon = _create_ai_dm_fixture()
    try:
        end_context = RoomAccessContext(
            room_id=fix_end.room_id,
            access_session_id=fix_end.owner_access_id,
            authority=RoomAccessAuthority.OWNER,
        )
        abandon_context = RoomAccessContext(
            room_id=fix_abandon.room_id,
            access_session_id=fix_abandon.owner_access_id,
            authority=RoomAccessAuthority.OWNER,
        )

        ended = fix_end.session_service.end_session(
            fix_end.room_id,
            fix_end.campaign_id,
            fix_end.session.id,
            end_context,
        )
        abandoned = fix_abandon.session_service.abandon_session(
            fix_abandon.room_id,
            fix_abandon.campaign_id,
            fix_abandon.session.id,
            abandon_context,
        )

        assert ended.status == SessionStatus.ENDED
        assert abandoned.status == SessionStatus.ABANDONED

        def _inspect_state(fix: AIDMSessionFixture) -> dict[str, object]:
            with fix.engine.connect() as conn:
                seats = conn.execute(
                    select(
                        campaign_seats.c.label,
                        campaign_seats.c.controller_kind,
                        campaign_seats.c.controller_access_session_id,
                        campaign_seats.c.ai_controller_grant_id,
                        campaign_seats.c.controller_epoch,
                    ).where(campaign_seats.c.id.in_([fix.dm_seat_id, fix.player_seat_id])).order_by(campaign_seats.c.label)
                ).mappings().all()
                grants = conn.execute(
                    select(
                        ai_controller_grants.c.role,
                        ai_controller_grants.c.status,
                        ai_controller_grants.c.temporary_instruction,
                    ).where(ai_controller_grants.c.session_id == fix.session.id).order_by(ai_controller_grants.c.role)
                ).mappings().all()
                leases_count = conn.scalar(
                    select(func.count()).select_from(active_character_session_leases).where(
                        active_character_session_leases.c.session_id == fix.session.id
                    )
                )
                last_event = conn.execute(
                    select(session_events).where(session_events.c.session_id == fix.session.id).order_by(session_events.c.seq.desc())
                ).mappings().first()
                sess = conn.execute(
                    select(sessions.c.status, sessions.c.ended_at).where(sessions.c.id == fix.session.id)
                ).mappings().one()
                return {
                    "seats": [dict(s) for s in seats],
                    "grants": [dict(g) for g in grants],
                    "leases_count": leases_count,
                    "session_ended_at_set": sess["ended_at"] is not None,
                    "session_status": sess["status"],
                    "event_kind": last_event["kind"],
                    "event_execution_mode": last_event["execution_mode"],
                    "event_acting_seat_id": last_event["acting_seat_id"],
                    "event_status": last_event["payload"]["status"],
                }

        state_end = _inspect_state(fix_end)
        state_abandon = _inspect_state(fix_abandon)

        assert state_end["seats"] == state_abandon["seats"]
        assert state_end["grants"] == state_abandon["grants"]
        assert state_end["leases_count"] == state_abandon["leases_count"] == 0
        assert state_end["session_ended_at_set"] is True
        assert state_abandon["session_ended_at_set"] is True
        assert state_end["event_execution_mode"] == state_abandon["event_execution_mode"] == "system"
        assert state_end["event_acting_seat_id"] == state_abandon["event_acting_seat_id"] is None

        assert state_end["session_status"] == "ended"
        assert state_abandon["session_status"] == "abandoned"
        assert state_end["event_kind"] == "session.ended"
        assert state_abandon["event_kind"] == "session.abandoned"
        assert state_end["event_status"] == "ended"
        assert state_abandon["event_status"] == "abandoned"
    finally:
        fix_end.engine.dispose()
        fix_abandon.engine.dispose()


def test_owner_end_human_dm_session_rejected_without_side_effects() -> None:
    fix = _create_human_dm_fixture(owner_is_dm=False)
    try:
        monitored_tables = [
            sessions,
            session_participants,
            campaign_seats,
            ai_controller_grants,
            session_events,
        ]
        with fix.engine.connect() as conn:
            counts_before = {
                table.name: conn.scalar(select(func.count()).select_from(table))
                for table in monitored_tables
            }
            epoch_before = conn.scalar(
                select(campaign_seats.c.controller_epoch).where(campaign_seats.c.id == fix.dm_seat_id)
            )

        owner_context = RoomAccessContext(
            room_id=fix.room_id,
            access_session_id=fix.owner_access_id,
            authority=RoomAccessAuthority.OWNER,
        )

        with pytest.raises(DMControllerMismatchError):
            fix.session_service.end_session(
                fix.room_id,
                fix.campaign_id,
                fix.session.id,
                owner_context,
            )

        with fix.engine.connect() as conn:
            counts_after = {
                table.name: conn.scalar(select(func.count()).select_from(table))
                for table in monitored_tables
            }
            epoch_after = conn.scalar(
                select(campaign_seats.c.controller_epoch).where(campaign_seats.c.id == fix.dm_seat_id)
            )
            sess = conn.execute(
                select(sessions.c.status, sessions.c.ended_at).where(sessions.c.id == fix.session.id)
            ).mappings().one()

        assert sess["status"] == "active"
        assert sess["ended_at"] is None
        assert counts_before == counts_after
        assert epoch_before == epoch_after
    finally:
        fix.engine.dispose()


def test_owner_who_is_current_human_dm_ends_via_dm_branch() -> None:
    fix = _create_human_dm_fixture(owner_is_dm=True)
    try:
        owner_context = RoomAccessContext(
            room_id=fix.room_id,
            access_session_id=fix.owner_access_id,
            authority=RoomAccessAuthority.OWNER,
        )
        ended = fix.session_service.end_session(
            fix.room_id,
            fix.campaign_id,
            fix.session.id,
            owner_context,
        )
        assert ended.status == SessionStatus.ENDED
        assert ended.ended_at is not None

        with fix.engine.connect() as conn:
            last_event = conn.execute(
                select(session_events).where(session_events.c.session_id == fix.session.id).order_by(session_events.c.seq.desc())
            ).mappings().first()

        assert last_event["kind"] == "session.ended"
        assert last_event["execution_mode"] == "self"
        assert last_event["acting_seat_id"] == fix.dm_seat_id
    finally:
        fix.engine.dispose()


def test_dm_key_holder_cannot_end_ai_dm_session() -> None:
    fix = _create_ai_dm_fixture()
    try:
        monitored_tables = [
            sessions,
            session_participants,
            campaign_seats,
            ai_controller_grants,
            session_events,
        ]
        with fix.engine.connect() as conn:
            counts_before = {
                table.name: conn.scalar(select(func.count()).select_from(table))
                for table in monitored_tables
            }
            dm_epoch_before = conn.scalar(
                select(campaign_seats.c.controller_epoch).where(campaign_seats.c.id == fix.dm_seat_id)
            )

        dm_context = RoomAccessContext(
            room_id=fix.room_id,
            access_session_id=fix.dm_access_id,
            authority=RoomAccessAuthority.DM,
        )

        with pytest.raises(DMControllerMismatchError):
            fix.session_service.end_session(
                fix.room_id,
                fix.campaign_id,
                fix.session.id,
                dm_context,
            )

        with fix.engine.connect() as conn:
            counts_after = {
                table.name: conn.scalar(select(func.count()).select_from(table))
                for table in monitored_tables
            }
            dm_epoch_after = conn.scalar(
                select(campaign_seats.c.controller_epoch).where(campaign_seats.c.id == fix.dm_seat_id)
            )
            sess = conn.execute(
                select(sessions.c.status, sessions.c.ended_at).where(sessions.c.id == fix.session.id)
            ).mappings().one()

        assert sess["status"] == "active"
        assert sess["ended_at"] is None
        assert counts_before == counts_after
        assert dm_epoch_before == dm_epoch_after
    finally:
        fix.engine.dispose()


def test_member_cannot_end_ai_dm_session() -> None:
    fix = _create_ai_dm_fixture()
    try:
        monitored_tables = [
            sessions,
            session_participants,
            campaign_seats,
            ai_controller_grants,
            session_events,
        ]
        with fix.engine.connect() as conn:
            counts_before = {
                table.name: conn.scalar(select(func.count()).select_from(table))
                for table in monitored_tables
            }
            dm_epoch_before = conn.scalar(
                select(campaign_seats.c.controller_epoch).where(campaign_seats.c.id == fix.dm_seat_id)
            )

        member_context = RoomAccessContext(
            room_id=fix.room_id,
            access_session_id=fix.member_access_id,
            authority=RoomAccessAuthority.MEMBER,
        )

        with pytest.raises(DMControllerMismatchError):
            fix.session_service.end_session(
                fix.room_id,
                fix.campaign_id,
                fix.session.id,
                member_context,
            )

        with fix.engine.connect() as conn:
            counts_after = {
                table.name: conn.scalar(select(func.count()).select_from(table))
                for table in monitored_tables
            }
            dm_epoch_after = conn.scalar(
                select(campaign_seats.c.controller_epoch).where(campaign_seats.c.id == fix.dm_seat_id)
            )
            sess = conn.execute(
                select(sessions.c.status, sessions.c.ended_at).where(sessions.c.id == fix.session.id)
            ).mappings().one()

        assert sess["status"] == "active"
        assert sess["ended_at"] is None
        assert counts_before == counts_after
        assert dm_epoch_before == dm_epoch_after
    finally:
        fix.engine.dispose()


def test_ai_dm_binding_rejected_after_owner_end() -> None:
    fix = _create_ai_dm_fixture()
    try:
        owner_context = RoomAccessContext(
            room_id=fix.room_id,
            access_session_id=fix.owner_access_id,
            authority=RoomAccessAuthority.OWNER,
        )
        ended = fix.session_service.end_session(
            fix.room_id,
            fix.campaign_id,
            fix.session.id,
            owner_context,
        )
        assert ended.status == SessionStatus.ENDED

        with pytest.raises(TableEventActorUnauthorizedError):
            fix.event_service.resolve_ai_actor(
                room_id=fix.room_id,
                campaign_id=fix.campaign_id,
                session_id=fix.session.id,
                grant_id=fix.dm_grant_id,
                generation=fix.dm_generation,
            )

        with pytest.raises(AIControllerUnauthorizedError):
            fix.controller_service.resolve_actor(fix.dm_token)

        with pytest.raises(AIControllerUnauthorizedError):
            fix.controller_service.resolve_actor(fix.player_token_plaintext)
    finally:
        fix.engine.dispose()


def test_after_owner_end_lobby_can_assign_human_dm_and_start() -> None:
    fix = _create_ai_dm_fixture()
    try:
        owner_context = RoomAccessContext(
            room_id=fix.room_id,
            access_session_id=fix.owner_access_id,
            authority=RoomAccessAuthority.OWNER,
        )
        ended = fix.session_service.end_session(
            fix.room_id,
            fix.campaign_id,
            fix.session.id,
            owner_context,
        )
        assert ended.status == SessionStatus.ENDED

        resume = fix.session_service.resume(fix.room_id, fix.campaign_id)
        assert resume.active_session is None

        now = datetime.now(timezone.utc)
        with fix.engine.begin() as connection:
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == fix.dm_seat_id)
                .values(
                    controller_kind="human",
                    controller_access_session_id=fix.owner_access_id,
                    controller_epoch=campaign_seats.c.controller_epoch + 1,
                    updated_at=now,
                )
            )

        new_session = fix.session_service.start_session(
            fix.room_id,
            fix.campaign_id,
            owner_context,
        )
        assert new_session.status == SessionStatus.ACTIVE
        assert new_session.dm_controller_kind == "human"
        assert new_session.dm_controller_access_session_id == fix.owner_access_id
    finally:
        fix.engine.dispose()


def test_owner_end_does_not_change_character_state() -> None:
    fix = _create_ai_dm_fixture()
    try:
        with fix.engine.connect() as conn:
            state_before = conn.execute(
                select(character_states.c.state_payload, character_states.c.state_revision).where(
                    character_states.c.character_id == fix.player_character_id
                )
            ).mappings().one()
            table_counts_before = {
                table.name: conn.scalar(select(func.count()).select_from(table))
                for table in metadata.tables.values()
            }

        owner_context = RoomAccessContext(
            room_id=fix.room_id,
            access_session_id=fix.owner_access_id,
            authority=RoomAccessAuthority.OWNER,
        )
        ended = fix.session_service.end_session(
            fix.room_id,
            fix.campaign_id,
            fix.session.id,
            owner_context,
        )
        assert ended.status == SessionStatus.ENDED

        with fix.engine.connect() as conn:
            state_after = conn.execute(
                select(character_states.c.state_payload, character_states.c.state_revision).where(
                    character_states.c.character_id == fix.player_character_id
                )
            ).mappings().one()
            table_counts_after = {
                table.name: conn.scalar(select(func.count()).select_from(table))
                for table in metadata.tables.values()
            }

        assert state_before["state_payload"] == state_after["state_payload"]
        assert state_before["state_revision"] == state_after["state_revision"]

        for table_name, count_before in table_counts_before.items():
            if table_name in {
                "active_character_session_leases",
                "session_events",
                "session_table_runtime",
            }:
                continue
            assert table_counts_after[table_name] == count_before, (
                f"Table {table_name} count changed: before={count_before}, after={table_counts_after[table_name]}"
            )
        assert table_counts_after["active_character_session_leases"] == 0
        assert table_counts_after["session_events"] == table_counts_before["session_events"] + 1
    finally:
        fix.engine.dispose()
