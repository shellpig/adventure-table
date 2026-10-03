from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Generator
from uuid import UUID, uuid4

from fastapi import Request
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import (
    create_engine,
    event,
    insert,
    update,
)
from sqlalchemy.engine import Engine
from sqlalchemy.pool import StaticPool

from app.api.dependencies import get_database_engine
from app.api.errors import APIError
from app.api.rooms.access import get_room_access_context
from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.dependencies import (
    get_monster_instance_service,
    get_monster_library_service,
    get_table_event_service,
)
from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.db import metadata
from app.domain.combat.ai_tools import CombatAIToolApplicationService
from app.domain.combat.initiative import CombatInitiativeService
from app.domain.combat.lifecycle import CombatService
from app.domain.combat.monster_instances import MonsterInstanceService
from app.domain.monster_library.schemas import CreateCustomMonsterInput
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import (
    AIControllerAuthView,
    AIControllerService,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_events import TableEventService
from app.main import app
from app.mcp.dependencies import get_ai_tool_application_service
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.mcp.tools import tool_catalog
from app.persistence.combat.initiative import CombatInitiativeRepository
from app.persistence.combat.lifecycle import CombatRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.tables import monster_instances
from app.persistence.monster_library.repository import MonsterLibraryRepository
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.sessions import SessionRepository
from app.persistence.rooms.table_runtime import TableEventRepository
from app.persistence.characters import characters
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    campaigns,
    room_access_sessions,
    rooms,
    session_participants,
    sessions,
)


def _engine() -> Engine:
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine, "connect")
    def _enable_foreign_keys(dbapi_connection, _connection_record) -> None:
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()

    metadata.create_all(engine)
    return engine


def _mcp_headers(method: str, *, name: str | None = None, token: str | None = None) -> dict[str, str]:
    headers = {
        "Content-Type": "application/json",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        headers["Mcp-Name"] = name
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _mcp_body(method: str, *, params: dict[str, object] | None = None, req_id: int = 1) -> dict[str, object]:
    merged = dict(params or {})
    merged["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "m07a-test", "version": "1"},
    }
    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "method": method,
        "params": merged,
    }


def _mcp_call(client: TestClient, token: str, name: str, arguments: dict[str, object]) -> dict[str, object]:
    resp = client.post(
        "/mcp",
        json=_mcp_body("tools/call", params={"name": name, "arguments": arguments}),
        headers=_mcp_headers("tools/call", name=name, token=token),
    )
    assert resp.status_code == 200, resp.text
    res = resp.json()
    assert "result" in res, f"Response missing result: {res}"
    return res["result"]


@dataclass(frozen=True)
class AuthFixture:
    client: TestClient
    engine: Engine
    room_id: UUID
    campaign_id: UUID
    session_id: UUID
    dm_seat_id: UUID
    player_seat_id: UUID
    # Room B (different room)
    room_b_id: UUID
    campaign_b_id: UUID
    session_b_id: UUID
    dm_seat_b_id: UUID
    # Tokens (Human)
    owner_token: str
    dm_token: str
    member_token: str
    dm_b_token: str
    owner_context: RoomAccessContext
    dm_context: RoomAccessContext
    member_context: RoomAccessContext
    dm_b_context: RoomAccessContext
    # Tokens (AI)
    ai_dm_token: str
    ai_player_token: str
    ai_presession_token: str
    ai_revoked_token: str
    ai_takenback_token: str
    ai_dm_b_token: str
    # Services
    library_service: MonsterLibraryService
    instance_service: MonsterInstanceService


@pytest.fixture
def auth_fixture() -> Generator[AuthFixture, None, None]:
    engine = _engine()
    registry = load_default_content_registry()
    content_root = resolve_content_root()
    localization = load_content_localization_catalog(registry, content_root)

    now = datetime.now(timezone.utc)
    room_id = uuid4()
    campaign_id = uuid4()
    session_id = uuid4()
    dm_seat_id = uuid4()
    player_seat_id = uuid4()

    # AI DM Campaign / Session in Room A
    ai_campaign_id = uuid4()
    ai_session_id = uuid4()
    ai_dm_seat_id = uuid4()
    ai_player_seat_id = uuid4()

    room_b_id = uuid4()
    campaign_b_id = uuid4()
    session_b_id = uuid4()
    dm_seat_b_id = uuid4()

    # AI DM Campaign / Session in Room B
    ai_campaign_b_id = uuid4()
    ai_session_b_id = uuid4()
    ai_dm_seat_b_id = uuid4()

    # Pre-session Room / Campaign
    pre_room_id = uuid4()
    pre_campaign_id = uuid4()
    pre_dm_seat_id = uuid4()

    owner_access_id = uuid4()
    dm_access_id = uuid4()
    member_access_id = uuid4()
    dm_b_access_id = uuid4()

    owner_token = "token-owner-secret"
    dm_token = "token-dm-secret"
    member_token = "token-member-secret"
    dm_b_token = "token-dm-b-secret"

    owner_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=owner_access_id,
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner A",
    )
    dm_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=dm_access_id,
        authority=RoomAccessAuthority.DM,
        display_name="Human DM A",
    )
    member_context = RoomAccessContext(
        room_id=room_id,
        access_session_id=member_access_id,
        authority=RoomAccessAuthority.MEMBER,
        display_name="Member A",
    )
    dm_b_context = RoomAccessContext(
        room_id=room_b_id,
        access_session_id=dm_b_access_id,
        authority=RoomAccessAuthority.DM,
        display_name="Human DM B",
    )

    token_map = {
        owner_token: owner_context,
        dm_token: dm_context,
        member_token: member_context,
        dm_b_token: dm_b_context,
    }

    # Mint AI controller tokens
    minted_ai_dm = mint_ai_controller_token()
    minted_ai_player = mint_ai_controller_token()
    minted_ai_presession = mint_ai_controller_token()
    minted_ai_revoked = mint_ai_controller_token()
    minted_ai_takenback = mint_ai_controller_token()
    minted_ai_dm_b = mint_ai_controller_token()

    with engine.begin() as conn:
        conn.exec_driver_sql("PRAGMA defer_foreign_keys = ON")
        # Seed Rooms
        conn.execute(
            insert(rooms).values(
                [
                    {
                        "id": room_id,
                        "code": "ROOMA",
                        "name": "Room A",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner_a",
                        "dm_key_hash": b"dm_a",
                        "active_campaign_id": ai_campaign_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": room_b_id,
                        "code": "ROOMB",
                        "name": "Room B",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner_b",
                        "dm_key_hash": b"dm_b",
                        "active_campaign_id": ai_campaign_b_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": pre_room_id,
                        "code": "ROMPRE",
                        "name": "Room Pre",
                        "password_salt": b"salt",
                        "password_hash": b"pw",
                        "owner_key_hash": b"owner_pre",
                        "dm_key_hash": b"dm_pre",
                        "active_campaign_id": pre_campaign_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

        # Seed Access Sessions
        conn.execute(
            insert(room_access_sessions).values(
                [
                    {
                        "id": owner_access_id,
                        "room_id": room_id,
                        "authority": "owner",
                        "token_hash": b"h_owner",
                        "display_name": "Owner A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": dm_access_id,
                        "room_id": room_id,
                        "authority": "dm",
                        "token_hash": b"h_dm",
                        "display_name": "Human DM A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": member_access_id,
                        "room_id": room_id,
                        "authority": "member",
                        "token_hash": b"h_member",
                        "display_name": "Member A",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                    {
                        "id": dm_b_access_id,
                        "room_id": room_b_id,
                        "authority": "dm",
                        "token_hash": b"h_dm_b",
                        "display_name": "Human DM B",
                        "created_at": now,
                        "last_seen_at": now,
                    },
                ]
            )
        )

        # Seed Campaigns
        conn.execute(
            insert(campaigns).values(
                [
                    {
                        "id": campaign_id,
                        "room_id": room_id,
                        "name": "Campaign A (Human)",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ai_campaign_id,
                        "room_id": room_id,
                        "name": "Campaign A (AI)",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": campaign_b_id,
                        "room_id": room_b_id,
                        "name": "Campaign B (Human)",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ai_campaign_b_id,
                        "room_id": room_b_id,
                        "name": "Campaign B (AI)",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": pre_campaign_id,
                        "room_id": pre_room_id,
                        "name": "Campaign Pre",
                        "ruleset": "dnd5e-2014",
                        "status": "active",
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

        char_id = uuid4()
        conn.execute(
            insert(characters).values(
                id=char_id,
                name="AI Player Character",
                ruleset="dnd5e-2014",
                created_at=now,
                updated_at=now,
            )
        )

        # Seed Seats
        conn.execute(
            insert(campaign_seats).values(
                [
                    {
                        "id": dm_seat_id,
                        "campaign_id": campaign_id,
                        "role": "dm",
                        "controller_kind": "human",
                        "controller_access_session_id": dm_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "selected_character_id": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": player_seat_id,
                        "campaign_id": campaign_id,
                        "role": "player",
                        "controller_kind": "human",
                        "controller_access_session_id": owner_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "selected_character_id": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ai_dm_seat_id,
                        "campaign_id": ai_campaign_id,
                        "role": "dm",
                        "controller_kind": "ai",
                        "controller_access_session_id": None,
                        "ai_controller_grant_id": minted_ai_dm.grant_id,
                        "controller_epoch": 1,
                        "selected_character_id": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ai_player_seat_id,
                        "campaign_id": ai_campaign_id,
                        "role": "player",
                        "controller_kind": "ai",
                        "controller_access_session_id": None,
                        "ai_controller_grant_id": minted_ai_player.grant_id,
                        "controller_epoch": 1,
                        "selected_character_id": char_id,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": dm_seat_b_id,
                        "campaign_id": campaign_b_id,
                        "role": "dm",
                        "controller_kind": "human",
                        "controller_access_session_id": dm_b_access_id,
                        "ai_controller_grant_id": None,
                        "controller_epoch": 1,
                        "selected_character_id": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": ai_dm_seat_b_id,
                        "campaign_id": ai_campaign_b_id,
                        "role": "dm",
                        "controller_kind": "ai",
                        "controller_access_session_id": None,
                        "ai_controller_grant_id": minted_ai_dm_b.grant_id,
                        "controller_epoch": 1,
                        "selected_character_id": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                    {
                        "id": pre_dm_seat_id,
                        "campaign_id": pre_campaign_id,
                        "role": "dm",
                        "controller_kind": "ai",
                        "controller_access_session_id": None,
                        "ai_controller_grant_id": minted_ai_presession.grant_id,
                        "controller_epoch": 1,
                        "selected_character_id": None,
                        "created_at": now,
                        "updated_at": now,
                    },
                ]
            )
        )

        # Seed Sessions
        conn.execute(
            insert(sessions).values(
                [
                    {
                        "id": session_id,
                        "campaign_id": campaign_id,
                        "status": "active",
                        "dm_seat_id": dm_seat_id,
                        "dm_controller_kind": "human",
                        "dm_controller_access_session_id": dm_access_id,
                        "dm_controller_ai_grant_id": None,
                        "dm_controller_generation": None,
                        "started_at": now,
                        "ended_at": None,
                        "created_at": now,
                    },
                    {
                        "id": ai_session_id,
                        "campaign_id": ai_campaign_id,
                        "status": "active",
                        "dm_seat_id": ai_dm_seat_id,
                        "dm_controller_kind": "ai",
                        "dm_controller_access_session_id": None,
                        "dm_controller_ai_grant_id": minted_ai_dm.grant_id,
                        "dm_controller_generation": 1,
                        "started_at": now,
                        "ended_at": None,
                        "created_at": now,
                    },
                    {
                        "id": session_b_id,
                        "campaign_id": campaign_b_id,
                        "status": "active",
                        "dm_seat_id": dm_seat_b_id,
                        "dm_controller_kind": "human",
                        "dm_controller_access_session_id": dm_b_access_id,
                        "dm_controller_ai_grant_id": None,
                        "dm_controller_generation": None,
                        "started_at": now,
                        "ended_at": None,
                        "created_at": now,
                    },
                    {
                        "id": ai_session_b_id,
                        "campaign_id": ai_campaign_b_id,
                        "status": "active",
                        "dm_seat_id": ai_dm_seat_b_id,
                        "dm_controller_kind": "ai",
                        "dm_controller_access_session_id": None,
                        "dm_controller_ai_grant_id": minted_ai_dm_b.grant_id,
                        "dm_controller_generation": 1,
                        "started_at": now,
                        "ended_at": None,
                        "created_at": now,
                    },
                ]
            )
        )

        # Seed Session Participants
        conn.execute(
            insert(session_participants).values(
                [
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": dm_seat_id,
                        "role_snapshot": "dm",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": dm_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": None,
                        "joined_at": now,
                        "left_at": None,
                    },
                    {
                        "id": uuid4(),
                        "session_id": session_id,
                        "seat_id": player_seat_id,
                        "role_snapshot": "player",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": owner_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": None,
                        "joined_at": now,
                        "left_at": None,
                    },
                    {
                        "id": uuid4(),
                        "session_id": ai_session_id,
                        "seat_id": ai_dm_seat_id,
                        "role_snapshot": "dm",
                        "controller_kind_at_join": "ai",
                        "controller_access_session_id_at_join": None,
                        "controller_ai_grant_id_at_join": minted_ai_dm.grant_id,
                        "controller_generation_at_join": 1,
                        "active_character_id": None,
                        "joined_at": now,
                        "left_at": None,
                    },
                    {
                        "id": uuid4(),
                        "session_id": ai_session_id,
                        "seat_id": ai_player_seat_id,
                        "role_snapshot": "player",
                        "controller_kind_at_join": "ai",
                        "controller_access_session_id_at_join": None,
                        "controller_ai_grant_id_at_join": minted_ai_player.grant_id,
                        "controller_generation_at_join": 1,
                        "active_character_id": char_id,
                        "joined_at": now,
                        "left_at": None,
                    },
                    {
                        "id": uuid4(),
                        "session_id": session_b_id,
                        "seat_id": dm_seat_b_id,
                        "role_snapshot": "dm",
                        "controller_kind_at_join": "human",
                        "controller_access_session_id_at_join": dm_b_access_id,
                        "controller_ai_grant_id_at_join": None,
                        "controller_generation_at_join": None,
                        "active_character_id": None,
                        "joined_at": now,
                        "left_at": None,
                    },
                    {
                        "id": uuid4(),
                        "session_id": ai_session_b_id,
                        "seat_id": ai_dm_seat_b_id,
                        "role_snapshot": "dm",
                        "controller_kind_at_join": "ai",
                        "controller_access_session_id_at_join": None,
                        "controller_ai_grant_id_at_join": minted_ai_dm_b.grant_id,
                        "controller_generation_at_join": 1,
                        "active_character_id": None,
                        "joined_at": now,
                        "left_at": None,
                    },
                ]
            )
        )

        # Seed AI Controller Grants
        conn.execute(
            insert(ai_controller_grants).values(
                [
                    # 1. Active AI DM for Room A
                    {
                        "id": minted_ai_dm.grant_id,
                        "room_id": room_id,
                        "campaign_id": ai_campaign_id,
                        "seat_id": ai_dm_seat_id,
                        "role": "dm",
                        "session_id": ai_session_id,
                        "secret_hash": minted_ai_dm.secret_hash,
                        "secret_prefix": minted_ai_dm.display_hint,
                        "generation": 1,
                        "status": "active",
                        "pre_session_expires_at": None,
                        "handoff_return_access_session_id": None,
                        "temporary_instruction": None,
                        "created_at": now,
                        "bound_at": now,
                        "revoked_at": None,
                        "last_seen_at": None,
                    },
                    # 2. Player AI Grant
                    {
                        "id": minted_ai_player.grant_id,
                        "room_id": room_id,
                        "campaign_id": ai_campaign_id,
                        "seat_id": ai_player_seat_id,
                        "role": "player",
                        "session_id": ai_session_id,
                        "secret_hash": minted_ai_player.secret_hash,
                        "secret_prefix": minted_ai_player.display_hint,
                        "generation": 1,
                        "status": "active",
                        "pre_session_expires_at": None,
                        "handoff_return_access_session_id": owner_access_id,
                        "temporary_instruction": None,
                        "created_at": now,
                        "bound_at": now,
                        "revoked_at": None,
                        "last_seen_at": None,
                    },
                    # 3. Pre-session DM Grant
                    {
                        "id": minted_ai_presession.grant_id,
                        "room_id": pre_room_id,
                        "campaign_id": pre_campaign_id,
                        "seat_id": pre_dm_seat_id,
                        "role": "dm",
                        "session_id": None,
                        "secret_hash": minted_ai_presession.secret_hash,
                        "secret_prefix": minted_ai_presession.display_hint,
                        "generation": 1,
                        "status": "active",
                        "pre_session_expires_at": now + timedelta(hours=1),
                        "handoff_return_access_session_id": None,
                        "temporary_instruction": None,
                        "created_at": now,
                        "bound_at": None,
                        "revoked_at": None,
                        "last_seen_at": None,
                    },
                    # 4. Revoked Grant
                    {
                        "id": minted_ai_revoked.grant_id,
                        "room_id": room_id,
                        "campaign_id": ai_campaign_id,
                        "seat_id": ai_dm_seat_id,
                        "role": "dm",
                        "session_id": ai_session_id,
                        "secret_hash": minted_ai_revoked.secret_hash,
                        "secret_prefix": minted_ai_revoked.display_hint,
                        "generation": 1,
                        "status": "revoked",
                        "pre_session_expires_at": None,
                        "handoff_return_access_session_id": None,
                        "temporary_instruction": None,
                        "created_at": now,
                        "bound_at": now,
                        "revoked_at": now,
                        "last_seen_at": None,
                    },
                    # 5. Taken-back Grant (stale generation / inactive seat)
                    {
                        "id": minted_ai_takenback.grant_id,
                        "room_id": room_id,
                        "campaign_id": campaign_id,
                        "seat_id": dm_seat_id,
                        "role": "dm",
                        "session_id": session_id,
                        "secret_hash": minted_ai_takenback.secret_hash,
                        "secret_prefix": minted_ai_takenback.display_hint,
                        "generation": 1,
                        "status": "active",
                        "pre_session_expires_at": None,
                        "handoff_return_access_session_id": None,
                        "temporary_instruction": None,
                        "created_at": now,
                        "bound_at": now,
                        "revoked_at": None,
                        "last_seen_at": None,
                    },
                    # 6. Active AI DM for Room B
                    {
                        "id": minted_ai_dm_b.grant_id,
                        "room_id": room_b_id,
                        "campaign_id": ai_campaign_b_id,
                        "seat_id": ai_dm_seat_b_id,
                        "role": "dm",
                        "session_id": ai_session_b_id,
                        "secret_hash": minted_ai_dm_b.secret_hash,
                        "secret_prefix": minted_ai_dm_b.display_hint,
                        "generation": 1,
                        "status": "active",
                        "pre_session_expires_at": None,
                        "handoff_return_access_session_id": None,
                        "temporary_instruction": None,
                        "created_at": now,
                        "bound_at": now,
                        "revoked_at": None,
                        "last_seen_at": None,
                    },
                ]
            )
        )

    # Instantiate services
    event_repo = TableEventRepository(engine)
    table_event_service = TableEventService(event_repo)
    monster_repo = MonsterRepository(engine)
    library_repo = MonsterLibraryRepository(engine)
    grant_repo = AIControllerGrantRepository(engine)
    ai_controller_service = AIControllerService(grant_repo, table_event_service)
    session_repo = SessionRepository(engine)
    session_service = SessionService(session_repo, event_service=table_event_service)

    library_service = MonsterLibraryService(
        engine=engine,
        repository=library_repo,
        monster_repository=monster_repo,
        content_registry=registry,
        localization=localization,
        table_event_service=table_event_service,
    )
    instance_service = MonsterInstanceService(
        monster_repository=monster_repo,
        content_registry=registry,
        table_event_service=table_event_service,
    )

    combat_repo = CombatRepository(engine, event_repo)
    combat_init_repo = CombatInitiativeRepository(engine, event_repo)
    combat_service = CombatService(
        combat_repo, table_event_service, object(), monster_repo, registry  # type: ignore[arg-type]
    )
    combat_init_service = CombatInitiativeService(
        combat_init_repo, combat_repo, combat_service, monster_repo, object(), table_event_service  # type: ignore[arg-type]
    )

    combat_ai_tool_service = CombatAIToolApplicationService(
        ai_controller_service=ai_controller_service,
        session_service=session_service,
        stage_service=object(),  # type: ignore[arg-type]
        action_service=object(),  # type: ignore[arg-type]
        roll_service=object(),  # type: ignore[arg-type]
        state_service=object(),  # type: ignore[arg-type]
        pending_action_service=object(),  # type: ignore[arg-type]
        event_service=table_event_service,
        workspace_service=object(),  # type: ignore[arg-type]
        combat_service=combat_service,
        combat_attack_service=object(),  # type: ignore[arg-type]
        combat_resolution_service=object(),  # type: ignore[arg-type]
        combat_core_roll_service=object(),  # type: ignore[arg-type]
        combat_special_attack_service=object(),  # type: ignore[arg-type]
        combat_initiative_service=combat_init_service,
        monster_instance_service=instance_service,
        combat_spell_service=object(),  # type: ignore[arg-type]
        combat_concentration_service=object(),  # type: ignore[arg-type]
        combat_reaction_service=object(),  # type: ignore[arg-type]
        combat_adjudication_service=object(),  # type: ignore[arg-type]
        monster_library_service=library_service,
    )

    # FastAPI dependency overrides
    def _override_access(request: Request) -> RoomAccessContext:
        auth_hdr = request.headers.get("authorization", "")
        _, _, tok = auth_hdr.partition(" ")
        clean = tok.strip()
        if clean in token_map:
            return token_map[clean]
        raise APIError(401, "room_access_required", "Room access required")

    app.dependency_overrides[get_room_access_context] = _override_access
    app.dependency_overrides[get_monster_library_service] = lambda: library_service
    app.dependency_overrides[get_monster_instance_service] = lambda: instance_service
    app.dependency_overrides[get_table_event_service] = lambda: table_event_service
    app.dependency_overrides[get_ai_controller_service] = lambda: ai_controller_service
    app.dependency_overrides[get_ai_tool_application_service] = lambda: combat_ai_tool_service
    app.dependency_overrides[get_database_engine] = lambda: engine
    app.state.content_registry = registry
    app.state.content_localization = localization
    app.state.ai_tool_application_service = combat_ai_tool_service

    client = TestClient(app)

    yield AuthFixture(
        client=client,
        engine=engine,
        room_id=room_id,
        campaign_id=campaign_id,
        session_id=session_id,
        dm_seat_id=dm_seat_id,
        player_seat_id=player_seat_id,
        room_b_id=room_b_id,
        campaign_b_id=campaign_b_id,
        session_b_id=session_b_id,
        dm_seat_b_id=dm_seat_b_id,
        owner_token=owner_token,
        dm_token=dm_token,
        member_token=member_token,
        dm_b_token=dm_b_token,
        owner_context=owner_context,
        dm_context=dm_context,
        member_context=member_context,
        dm_b_context=dm_b_context,
        ai_dm_token=minted_ai_dm.plaintext,
        ai_player_token=minted_ai_player.plaintext,
        ai_presession_token=minted_ai_presession.plaintext,
        ai_revoked_token=minted_ai_revoked.plaintext,
        ai_takenback_token=minted_ai_takenback.plaintext,
        ai_dm_b_token=minted_ai_dm_b.plaintext,
        library_service=library_service,
        instance_service=instance_service,
    )

    app.dependency_overrides.clear()
    app.state.ai_tool_application_service = None
    engine.dispose()


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# 1. Human DM and AI DM (MCP dispatch) create Instances from custom:<uuid>
# =============================================================================

def test_human_and_ai_dm_create_instance_from_custom_template_same_room(auth_fixture: AuthFixture) -> None:
    fix = auth_fixture

    # Create custom monster template in Room A
    t = fix.library_service.create_custom(
        fix.owner_context,
        fix.room_id,
        CreateCustomMonsterInput(
            name="Shadow Stalker",
            armor_class=14,
            max_hp=45,
            actions=[{"name": "Shadow Strike", "desc": "Deals 2d6 cold damage."}],
        ),
    )
    t_id = t.ref.removeprefix("custom:")
    t_uuid = UUID(t_id)

    # (A) Human DM creates instance via REST /from-content
    human_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/monster-instances/from-content",
        json={"content_key": f"custom:{t_id}"},
        headers=_auth(fix.dm_token),
    )
    assert human_resp.status_code == 200 or human_resp.status_code == 201
    h_inst = human_resp.json()
    assert h_inst["name"] == "Shadow Stalker"
    assert h_inst["custom_template_id"] == t_id
    assert h_inst["current_hp"] == 45
    assert h_inst["rules_snapshot"]["armor_class"] == 14

    # (B) AI DM creates instance via MCP dispatch
    ai_result = _mcp_call(
        fix.client,
        fix.ai_dm_token,
        "combat_create_monster",
        {"content_key": f"custom:{t_id}", "idempotency_key": "ai-inst-shadow-1"},
    )
    assert ai_result["isError"] is False
    ai_inst = ai_result["structuredContent"]["data"]
    assert ai_inst["name"] == "Shadow Stalker"
    assert ai_inst["custom_template_id"] == t_id
    assert ai_inst["current_hp"] == 45
    assert ai_inst["rules_snapshot"]["armor_class"] == 14


# =============================================================================
# 2. Target Campaign must be in the same Room (cross-room rejected)
# =============================================================================

def test_create_instance_from_custom_template_cross_room_rejected(auth_fixture: AuthFixture) -> None:
    fix = auth_fixture

    # Template in Room A
    t_a = fix.library_service.create_custom(
        fix.owner_context,
        fix.room_id,
        CreateCustomMonsterInput(name="Room A Exclusive", armor_class=10, max_hp=20),
    )
    t_a_id = t_a.ref.removeprefix("custom:")

    # (A) Human DM attempting to create in Campaign B (which is in Room B) using Template A
    human_b_resp = fix.client.post(
        f"/api/rooms/{fix.room_b_id}/campaigns/{fix.campaign_b_id}/sessions/{fix.session_b_id}/monster-instances/from-content",
        json={"content_key": f"custom:{t_a_id}"},
        headers=_auth(fix.dm_b_token),
    )
    # Fails 404 (template not found in Room B)
    assert human_b_resp.status_code == 404
    assert human_b_resp.json()["error"]["code"] == "monster_template_not_found"

    # (B) AI DM in Room B calls MCP combat_create_monster with Template A
    ai_b_result = _mcp_call(
        fix.client,
        fix.ai_dm_b_token,
        "combat_create_monster",
        {"content_key": f"custom:{t_a_id}", "idempotency_key": "ai-cross-room-fail"},
    )
    assert ai_b_result["isError"] is True
    assert ai_b_result["structuredContent"]["error"]["code"] == "not_found"


# =============================================================================
# 3. Editing the template does not change an existing Instance's HP/resources/abilities
# =============================================================================

def test_editing_template_does_not_mutate_existing_instance(auth_fixture: AuthFixture) -> None:
    fix = auth_fixture

    # Create template with AC 12, max_hp 30
    t = fix.library_service.create_custom(
        fix.owner_context,
        fix.room_id,
        CreateCustomMonsterInput(
            name="Mutating Beast",
            armor_class=12,
            max_hp=30,
            traits=[{"name": "Original Trait", "desc": "Initial power"}],
        ),
    )
    t_id = t.ref.removeprefix("custom:")

    # Create instance from template
    create_resp = fix.client.post(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/monster-instances/from-content",
        json={"content_key": f"custom:{t_id}"},
        headers=_auth(fix.dm_token),
    )
    assert create_resp.status_code in (200, 201), create_resp.text
    inst_data = create_resp.json()
    inst_id = inst_data["id"]

    # Mutate instance: damage instance so current_hp becomes 12
    with fix.engine.begin() as conn:
        conn.execute(
            update(monster_instances)
            .where(monster_instances.c.id == UUID(inst_id))
            .values(current_hp=12, temp_hp=5)
        )

    # Patch the custom template in the library: change AC to 18, max_hp to 100, add new trait
    patch_resp = fix.client.patch(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{t_id}",
        json={
            "expected_revision": 1,
            "name": "Evolved Beast",
            "armor_class": 18,
            "max_hp": 100,
            "traits": [{"name": "Evolved Trait", "desc": "Massive boost"}],
        },
        headers=_auth(fix.owner_token),
    )
    assert patch_resp.status_code == 200
    patched_t = patch_resp.json()
    assert patched_t["revision"] == 2
    assert patched_t["rules"]["armor_class"] == 18
    assert patched_t["rules"]["max_hp"] == 100

    # Fetch existing instance from instances list
    list_inst_resp = fix.client.get(
        f"/api/rooms/{fix.room_id}/campaigns/{fix.campaign_id}/sessions/{fix.session_id}/monster-instances",
        headers=_auth(fix.dm_token),
    )
    assert list_inst_resp.status_code == 200
    inst_list = list_inst_resp.json()
    found = next(item for item in inst_list if item["id"] == inst_id)

    # Assert existing instance rules, snapshot, HP, and resources are completely untouched
    assert found["current_hp"] == 12
    assert found["temp_hp"] == 5
    assert found["rules_snapshot"]["armor_class"] == 12
    assert found["rules_snapshot"]["max_hp"] == 30
    assert found["rules_snapshot"]["traits"][0]["name"] == "Original Trait"


# =============================================================================
# 4. AI cannot save to the library & AI token rejected on library REST
# =============================================================================

def test_ai_cannot_save_to_library_and_ai_token_rejected_on_rest(auth_fixture: AuthFixture) -> None:
    fix = auth_fixture

    # Verify no tool exists in MCP tool_catalog that can create or save monster templates
    auth_dm = AIControllerAuthView(
        grant_id=uuid4(),
        room_id=fix.room_id,
        campaign_id=fix.campaign_id,
        seat_id=fix.dm_seat_id,
        role="dm",
        session_id=fix.session_id,
        generation=1,
        is_current_dm=True,
        temporary_instruction=None,
    )
    tools = tool_catalog(auth_dm)
    tool_names = {t["name"] for t in tools}

    forbidden_tool_names = {
        "monster_library_create",
        "monster_library_save",
        "monster_library_patch",
        "monster_library_delete",
        "monster_library_archive",
        "monster_library_copy",
        "save_instance_as_template",
    }
    assert not (tool_names & forbidden_tool_names), f"Found forbidden AI write tools: {tool_names & forbidden_tool_names}"

    # REST endpoint rejects AI token
    create_r = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom",
        json={"name": "AI Illegally Created Monster", "armor_class": 10, "max_hp": 10},
        headers=_auth(fix.ai_dm_token),
    )
    assert create_r.status_code == 401
    assert create_r.json()["error"]["code"] == "room_access_required"

    from_inst_r = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/from-instance",
        json={"instance_id": str(uuid4()), "name": "AI Saved Instance"},
        headers=_auth(fix.ai_dm_token),
    )
    assert from_inst_r.status_code == 401
    assert from_inst_r.json()["error"]["code"] == "room_access_required"


# =============================================================================
# 5. AI read access control: Player, pre-session, revoked, taken-back
# =============================================================================

def test_ai_read_grants_access_control(auth_fixture: AuthFixture) -> None:
    fix = auth_fixture

    # First seed a custom template so library is not empty
    t = fix.library_service.create_custom(
        fix.owner_context,
        fix.room_id,
        CreateCustomMonsterInput(name="Library Guard", armor_class=15, max_hp=50),
    )
    t_id = t.ref

    # (A) Player AI Grant
    r_list_player = _mcp_call(fix.client, fix.ai_player_token, "monster_library_list", {})
    assert r_list_player["isError"] is True
    assert r_list_player["structuredContent"]["error"]["code"] == "permission_denied"

    r_get_player = _mcp_call(fix.client, fix.ai_player_token, "monster_library_get", {"ref": t_id})
    assert r_get_player["isError"] is True
    assert r_get_player["structuredContent"]["error"]["code"] == "permission_denied"

    # (B) Pre-session DM Grant (session_id is None)
    r_list_pre = _mcp_call(fix.client, fix.ai_presession_token, "monster_library_list", {})
    assert r_list_pre["isError"] is True

    r_get_pre = _mcp_call(fix.client, fix.ai_presession_token, "monster_library_get", {"ref": t_id})
    assert r_get_pre["isError"] is True

    # (C) Revoked Grant
    # MCP auth endpoint raises 401 or returns tool error
    resp_revoked = fix.client.post(
        "/mcp",
        json=_mcp_body("tools/call", params={"name": "monster_library_list", "arguments": {}}),
        headers=_mcp_headers("tools/call", name="monster_library_list", token=fix.ai_revoked_token),
    )
    assert resp_revoked.status_code in (200, 401)
    if resp_revoked.status_code == 200:
        res = resp_revoked.json()["result"]
        assert res["isError"] is True
        assert res["structuredContent"]["error"]["code"] == "permission_denied"

    # (D) Taken-back Grant
    resp_takenback = fix.client.post(
        "/mcp",
        json=_mcp_body("tools/call", params={"name": "monster_library_list", "arguments": {}}),
        headers=_mcp_headers("tools/call", name="monster_library_list", token=fix.ai_takenback_token),
    )
    assert resp_takenback.status_code in (200, 401)
    if resp_takenback.status_code == 200:
        res = resp_takenback.json()["result"]
        assert res["isError"] is True
        assert res["structuredContent"]["error"]["code"] == "permission_denied"

    # (E) Active DM Grant succeeds
    r_list_dm = _mcp_call(fix.client, fix.ai_dm_token, "monster_library_list", {"query": "Library Guard"})
    assert r_list_dm["isError"] is False
    templates = r_list_dm["structuredContent"]["data"]["templates"]
    assert any(item["name"] == "Library Guard" for item in templates)

    r_get_dm = _mcp_call(fix.client, fix.ai_dm_token, "monster_library_get", {"ref": t_id})
    assert r_get_dm["isError"] is False
    detail = r_get_dm["structuredContent"]["data"]
    assert detail["name"] == "Library Guard"
    assert detail["rules"]["armor_class"] == 15


# =============================================================================
# 6. Human Room Authority matrix
# =============================================================================

def test_human_room_authority_matrix(auth_fixture: AuthFixture) -> None:
    fix = auth_fixture

    # (A) Member is 403 on library REST (monster_library_forbidden)
    # Create custom
    r_create = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom",
        json={"name": "Member Monster", "armor_class": 10, "max_hp": 10},
        headers=_auth(fix.member_token),
    )
    assert r_create.status_code == 403
    assert r_create.json()["error"]["code"] == "monster_library_forbidden"

    # List
    r_list = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library",
        headers=_auth(fix.member_token),
    )
    assert r_list.status_code == 403
    assert r_list.json()["error"]["code"] == "monster_library_forbidden"

    # Get detail
    r_get = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library/srd5.1:monster:goblin",
        headers=_auth(fix.member_token),
    )
    assert r_get.status_code == 403
    assert r_get.json()["error"]["code"] == "monster_library_forbidden"

    # Patch
    dummy_id = uuid4()
    r_patch = fix.client.patch(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{dummy_id}",
        json={"expected_revision": 1, "armor_class": 12},
        headers=_auth(fix.member_token),
    )
    assert r_patch.status_code == 403
    assert r_patch.json()["error"]["code"] == "monster_library_forbidden"

    # Delete
    r_del = fix.client.delete(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{dummy_id}?expected_revision=1",
        headers=_auth(fix.member_token),
    )
    assert r_del.status_code == 403
    assert r_del.json()["error"]["code"] == "monster_library_forbidden"

    # Archive
    r_arch = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{dummy_id}/archive",
        json={"expected_revision": 1},
        headers=_auth(fix.member_token),
    )
    assert r_arch.status_code == 403
    assert r_arch.json()["error"]["code"] == "monster_library_forbidden"

    # Copy
    r_copy = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom/{dummy_id}/copy",
        json={"expected_revision": 1, "name": "Copied"},
        headers=_auth(fix.member_token),
    )
    assert r_copy.status_code == 403
    assert r_copy.json()["error"]["code"] == "monster_library_forbidden"

    # (B) Room Owner sitting in Player Seat still manages library
    # Owner token is assigned to player_seat_id in campaign_seats
    owner_create = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom",
        json={"name": "Owner In Player Seat Monster", "armor_class": 13, "max_hp": 35},
        headers=_auth(fix.owner_token),
    )
    assert owner_create.status_code == 201
    owner_t = owner_create.json()
    assert owner_t["name"] == "Owner In Player Seat Monster"

    owner_list = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library",
        headers=_auth(fix.owner_token),
    )
    assert owner_list.status_code == 200

    # (C) Non-DM-Seat actor with only Room DM authority still manages it via REST
    # Human DM has RoomAccessAuthority.DM, but DM seat is controlled by AI in this session
    dm_create = fix.client.post(
        f"/api/rooms/{fix.room_id}/monster-library/custom",
        json={"name": "Room DM Authority Monster", "armor_class": 16, "max_hp": 55},
        headers=_auth(fix.dm_token),
    )
    assert dm_create.status_code == 201
    dm_t = dm_create.json()
    assert dm_t["name"] == "Room DM Authority Monster"

    dm_list = fix.client.get(
        f"/api/rooms/{fix.room_id}/monster-library",
        headers=_auth(fix.dm_token),
    )
    assert dm_list.status_code == 200
