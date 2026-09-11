from __future__ import annotations

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy import insert, update

from app.domain.rooms.ai_controllers import AIControllerService, AIHandoffRequest
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import SessionService, SessionStatus
from app.domain.rooms.table_events import TableEventService
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    sessions,
)
from tests.test_p3e_mcp_token_lifecycle import (
    _assert_unauthorized,
    _client,
    _discover,
)
from tests.test_p3e_shared_action_integration import _engine, _seed


def _handoff(engine):
    ids = _seed(engine)
    events = TableEventService(TableEventRepository(engine))
    controller = AIControllerService(AIControllerGrantRepository(engine), events)
    grant = controller.let_ai_control_player(
        room_id=ids["room_id"],
        campaign_id=ids["campaign_id"],
        session_id=ids["session_id"],
        seat_id=ids["player_seat_id"],
        context=RoomAccessContext(
            room_id=ids["room_id"],
            access_session_id=ids["player_access_id"],
            authority=RoomAccessAuthority.MEMBER,
        ),
        request=AIHandoffRequest(temporary_instruction="Keep the scout safe."),
    )
    return ids, events, controller, grant


def _context_call(client, token: str):
    return client.post(
        "/mcp",
        json={
            "jsonrpc": "2.0",
            "id": "context-after-lifecycle",
            "method": "tools/call",
            "params": {
                "name": "get_session_context",
                "arguments": {},
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
                    "io.modelcontextprotocol/clientCapabilities": {},
                },
            },
        },
        headers={
            "Authorization": f"Bearer {token}",
            "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
            "Mcp-Method": "tools/call",
            "Mcp-Name": "get_session_context",
        },
    )


def test_mcp_token_is_rejected_immediately_after_human_dm_ends_session() -> None:
    engine = _engine()
    try:
        ids, events, controller, grant = _handoff(engine)
        client = _client(controller)
        try:
            assert _discover(client, grant.token).status_code == 200

            session_service = SessionService(
                SessionRepository(engine),
                event_service=events,
            )
            ended = session_service.end_session(
                ids["room_id"],
                ids["campaign_id"],
                ids["session_id"],
                RoomAccessContext(
                    room_id=ids["room_id"],
                    access_session_id=ids["dm_access_id"],
                    authority=RoomAccessAuthority.DM,
                ),
            )
            assert ended.status is SessionStatus.ENDED

            _assert_unauthorized(_context_call(client, grant.token))
        finally:
            client.close()
    finally:
        engine.dispose()


def test_mcp_token_is_rejected_after_administrative_human_reassignment() -> None:
    engine = _engine()
    try:
        ids, _events, controller, grant = _handoff(engine)
        replacement_access_id = uuid4()
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                insert(room_access_sessions).values(
                    id=replacement_access_id,
                    room_id=ids["room_id"],
                    authority="member",
                    token_hash=b"r" * 32,
                    display_name="Replacement Player",
                    created_at=now,
                    last_seen_at=now,
                    revoked_at=None,
                )
            )

        client = _client(controller)
        try:
            assert _discover(client, grant.token).status_code == 200

            controller.administratively_reassign_player(
                room_id=ids["room_id"],
                campaign_id=ids["campaign_id"],
                session_id=ids["session_id"],
                seat_id=ids["player_seat_id"],
                target_access_session_id=replacement_access_id,
                admin_context=RoomAccessContext(
                    room_id=ids["room_id"],
                    access_session_id=ids["dm_access_id"],
                    authority=RoomAccessAuthority.DM,
                ),
            )

            _assert_unauthorized(_context_call(client, grant.token))
        finally:
            client.close()
    finally:
        engine.dispose()


def test_mcp_rejects_grant_if_its_session_binding_points_to_another_campaign() -> None:
    engine = _engine()
    try:
        ids, _events, controller, grant = _handoff(engine)
        wrong_campaign_id = uuid4()
        wrong_dm_seat_id = uuid4()
        wrong_session_id = uuid4()
        now = datetime.now(timezone.utc)
        with engine.begin() as connection:
            connection.execute(
                insert(campaigns).values(
                    id=wrong_campaign_id,
                    room_id=ids["room_id"],
                    name="Wrong Session Campaign",
                    ruleset="dnd5e-2014",
                    status="active",
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(campaign_seats).values(
                    id=wrong_dm_seat_id,
                    campaign_id=wrong_campaign_id,
                    role="dm",
                    label="Wrong DM",
                    controller_kind="none",
                    controller_access_session_id=None,
                    ai_controller_grant_id=None,
                    controller_epoch=0,
                    selected_character_id=None,
                    archived_at=None,
                    created_at=now,
                    updated_at=now,
                )
            )
            connection.execute(
                insert(sessions).values(
                    id=wrong_session_id,
                    campaign_id=wrong_campaign_id,
                    status="active",
                    dm_seat_id=wrong_dm_seat_id,
                    dm_controller_kind="none",
                    dm_controller_access_session_id=None,
                    dm_controller_ai_grant_id=None,
                    dm_controller_generation=None,
                    started_at=now,
                    ended_at=None,
                    created_at=now,
                )
            )

        client = _client(controller)
        try:
            assert _discover(client, grant.token).status_code == 200
            with engine.begin() as connection:
                connection.execute(
                    update(ai_controller_grants)
                    .where(ai_controller_grants.c.id == grant.grant_id)
                    .values(session_id=wrong_session_id)
                )

            _assert_unauthorized(_context_call(client, grant.token))
        finally:
            client.close()
    finally:
        engine.dispose()
