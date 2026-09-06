from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, update
from sqlalchemy.pool import StaticPool

from app.db import metadata
from app.domain.rooms.access import (
    FixedWindowThrottle,
    ROOM_CODE_ALPHABET,
    generate_password_salt,
    hash_password,
    normalize_room_code,
    verify_password,
)
from app.domain.rooms.service import RoomService
from app.main import app
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import room_access_sessions, rooms


def _client(*, service: RoomService | None = None):
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    app.state.character_engine = engine
    app.state.room_service = service
    app.state.room_access_throttle = FixedWindowThrottle()
    return TestClient(app), engine


def _create_room(client: TestClient, *, name: str = "Sunday Table", password: str = "secret pass") -> dict:
    response = client.post(
        "/api/rooms",
        json={"name": name, "password": password, "display_name": "Host"},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_room_code_and_password_policy_are_stable() -> None:
    assert normalize_room_code(" 0123456789 ") == "0123456789"
    for bad in ("SHORT", "01234I6789", "01234L6789", "01234O6789", "01234U6789"):
        try:
            normalize_room_code(bad)
        except ValueError:
            pass
        else:
            raise AssertionError(f"invalid Room code accepted: {bad}")

    salt = generate_password_salt()
    hashed = hash_password("  secret  ", salt)
    assert verify_password("  secret  ", salt, hashed)
    assert not verify_password("secret", salt, hashed)


def test_create_room_returns_one_time_secrets_and_persists_hashes_only() -> None:
    client, engine = _client()
    grant = _create_room(client)

    code = grant["room"]["code"]
    assert len(code) == 10
    assert set(code) <= set(ROOM_CODE_ALPHABET)
    assert grant["authority"] == "owner"
    assert grant["owner_key"]
    assert grant["dm_key"]
    assert grant["access_token"]

    with engine.connect() as connection:
        room_row = connection.execute(select(rooms)).mappings().one()
        access_row = connection.execute(select(room_access_sessions)).mappings().one()
    assert isinstance(room_row["password_hash"], bytes)
    assert isinstance(room_row["owner_key_hash"], bytes)
    assert isinstance(room_row["dm_key_hash"], bytes)
    assert isinstance(access_row["token_hash"], bytes)
    stored_bytes = b"".join(
        [room_row["password_hash"], room_row["owner_key_hash"], room_row["dm_key_hash"], access_row["token_hash"]]
    )
    for secret in ("secret pass", grant["owner_key"], grant["dm_key"], grant["access_token"]):
        assert secret.encode("utf-8") not in stored_bytes
    engine.dispose()


def test_enter_room_normalizes_code_and_assigns_member_dm_owner_authority() -> None:
    client, engine = _client()
    created = _create_room(client)
    code = created["room"]["code"]

    member = client.post(
        "/api/rooms/enter",
        json={"code": code.lower(), "password": "secret pass", "display_name": "Player"},
    )
    assert member.status_code == 201, member.text
    assert member.json()["authority"] == "member"
    assert member.json()["owner_key"] is None
    assert member.json()["dm_key"] is None

    dm = client.post(
        "/api/rooms/enter",
        json={"code": code, "password": "secret pass", "elevated_key": created["dm_key"]},
    )
    assert dm.status_code == 201, dm.text
    assert dm.json()["authority"] == "dm"

    owner = client.post(
        "/api/rooms/enter",
        json={"code": code, "password": "secret pass", "elevated_key": created["owner_key"]},
    )
    assert owner.status_code == 201, owner.text
    assert owner.json()["authority"] == "owner"
    engine.dispose()


def test_room_scope_required_and_heartbeat_contract() -> None:
    client, engine = _client()
    first = _create_room(client, name="First")
    second = _create_room(client, name="Second")
    room_id = first["room"]["id"]
    headers = {"Authorization": f"Bearer {first['access_token']}"}

    missing = client.post(f"/api/rooms/{room_id}/access/heartbeat")
    assert missing.status_code == 401
    assert missing.json()["error"]["code"] == "room_access_required"

    mismatch = client.post(
        f"/api/rooms/{second['room']['id']}/access/heartbeat",
        headers=headers,
    )
    assert mismatch.status_code == 403
    assert mismatch.json()["error"]["code"] == "room_scope_mismatch"

    before = datetime.now(timezone.utc)
    heartbeat = client.post(f"/api/rooms/{room_id}/access/heartbeat", headers=headers)
    assert heartbeat.status_code == 200, heartbeat.text
    assert heartbeat.json()["ok"] is True
    with engine.connect() as connection:
        touched = connection.execute(
            select(room_access_sessions.c.last_seen_at).where(
                room_access_sessions.c.id == first["access_session_id"]
            )
        ).scalar_one()
    touched_utc = touched.replace(tzinfo=timezone.utc) if touched.tzinfo is None else touched
    assert touched_utc >= before - timedelta(seconds=1)

    with engine.begin() as connection:
        connection.execute(
            update(room_access_sessions)
            .where(room_access_sessions.c.id == first["access_session_id"])
            .values(revoked_at=datetime.now(timezone.utc))
        )
    revoked = client.post(f"/api/rooms/{room_id}/access/heartbeat", headers=headers)
    assert revoked.status_code == 401
    assert revoked.json()["error"]["code"] == "room_access_revoked"
    engine.dispose()


def test_failed_room_access_is_throttled_after_ten_failures_and_success_clears_window() -> None:
    ticks = [0.0]
    throttle = FixedWindowThrottle(clock=lambda: ticks[0])
    client, engine = _client()
    app.state.room_access_throttle = throttle
    created = _create_room(client)
    code = created["room"]["code"]

    for _ in range(10):
        denied = client.post(
            "/api/rooms/enter",
            json={"code": code, "password": "wrong password"},
        )
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "room_access_denied"

    throttled = client.post(
        "/api/rooms/enter",
        json={"code": code, "password": "secret pass"},
    )
    assert throttled.status_code == 429
    assert throttled.json()["error"]["code"] == "room_access_throttled"

    ticks[0] += 301.0
    success = client.post(
        "/api/rooms/enter",
        json={"code": code, "password": "secret pass"},
    )
    assert success.status_code == 201, success.text
    engine.dispose()
