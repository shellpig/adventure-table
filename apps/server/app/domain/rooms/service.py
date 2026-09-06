from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.domain.rooms.access import (
    FixedWindowThrottle,
    generate_password_salt,
    generate_room_code,
    generate_secret,
    hash_password,
    hash_secret,
    normalize_room_code,
    verify_password,
    verify_secret,
)
from app.domain.rooms.schemas import (
    CreateRoomRequest,
    EnterRoomRequest,
    Room,
    RoomAccessAuthority,
    RoomAccessContext,
    RoomAccessGrant,
)
from app.persistence.rooms.repository import (
    RoomPersistenceConflictError,
    RoomRepository,
    StoredAccessSession,
    StoredRoom,
)


class RoomNotFoundError(LookupError):
    pass


class RoomAccessDeniedError(PermissionError):
    pass


class RoomAccessThrottledError(PermissionError):
    pass


class RoomScopeMismatchError(PermissionError):
    pass


class RoomAccessRevokedError(PermissionError):
    pass


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _room_view(room: StoredRoom) -> Room:
    return Room(
        id=room.id,
        code=room.code,
        name=room.name,
        created_at=room.created_at,
        updated_at=room.updated_at,
    )


class RoomService:
    def __init__(
        self,
        repository: RoomRepository,
        *,
        throttle: FixedWindowThrottle | None = None,
        clock: Callable[[], datetime] = _utcnow,
    ) -> None:
        self.repository = repository
        self.throttle = throttle or FixedWindowThrottle()
        self.clock = clock

    def create_room(self, request: CreateRoomRequest) -> RoomAccessGrant:
        owner_key = generate_secret()
        dm_key = generate_secret()
        access_token = generate_secret()
        salt = generate_password_salt()
        now = self.clock()

        for _ in range(8):
            room_id = uuid4()
            access_session_id = uuid4()
            room = StoredRoom(
                id=room_id,
                code=generate_room_code(),
                name=request.name,
                password_salt=salt,
                password_hash=hash_password(request.password, salt),
                owner_key_hash=hash_secret(owner_key),
                dm_key_hash=hash_secret(dm_key),
                created_at=now,
                updated_at=now,
            )
            access = StoredAccessSession(
                id=access_session_id,
                room_id=room_id,
                authority=RoomAccessAuthority.OWNER,
                token_hash=hash_secret(access_token),
                display_name=request.display_name,
                created_at=now,
                last_seen_at=now,
                revoked_at=None,
            )
            try:
                self.repository.create_room_with_access(room=room, access=access)
            except RoomPersistenceConflictError:
                continue
            return RoomAccessGrant(
                room=_room_view(room),
                authority=RoomAccessAuthority.OWNER,
                access_session_id=access_session_id,
                access_token=access_token,
                owner_key=owner_key,
                dm_key=dm_key,
            )
        raise RuntimeError("unable to allocate unique Room credentials")

    def enter_room(self, request: EnterRoomRequest, *, remote_addr: str) -> RoomAccessGrant:
        try:
            code = normalize_room_code(request.code)
        except ValueError as exc:
            raise RoomNotFoundError(request.code) from exc
        throttle_key = (code, remote_addr)
        if self.throttle.blocked(throttle_key):
            raise RoomAccessThrottledError(code)

        room = self.repository.get_room_by_code(code)
        if room is None:
            raise RoomNotFoundError(code)
        if not verify_password(request.password, room.password_salt, room.password_hash):
            self.throttle.record_failure(throttle_key)
            raise RoomAccessDeniedError("invalid room password")

        authority = RoomAccessAuthority.MEMBER
        if request.elevated_key is not None:
            if verify_secret(request.elevated_key, room.owner_key_hash):
                authority = RoomAccessAuthority.OWNER
            elif verify_secret(request.elevated_key, room.dm_key_hash):
                authority = RoomAccessAuthority.DM
            else:
                self.throttle.record_failure(throttle_key)
                raise RoomAccessDeniedError("invalid elevated Room key")

        for _ in range(4):
            token = generate_secret()
            session = StoredAccessSession(
                id=uuid4(),
                room_id=room.id,
                authority=authority,
                token_hash=hash_secret(token),
                display_name=request.display_name,
                created_at=self.clock(),
                last_seen_at=self.clock(),
                revoked_at=None,
            )
            try:
                self.repository.create_access_session(session)
            except RoomPersistenceConflictError:
                continue
            self.throttle.clear(throttle_key)
            return RoomAccessGrant(
                room=_room_view(room),
                authority=authority,
                access_session_id=session.id,
                access_token=token,
            )
        raise RuntimeError("unable to allocate unique Room access token")

    def authenticate(self, room_id: UUID, access_token: str) -> RoomAccessContext:
        session = self.repository.get_access_session_by_token_hash(hash_secret(access_token))
        if session is None:
            raise RoomAccessDeniedError("invalid Room access token")
        if session.revoked_at is not None:
            raise RoomAccessRevokedError(str(session.id))
        if session.room_id != room_id:
            raise RoomScopeMismatchError(str(room_id))
        return RoomAccessContext(
            room_id=session.room_id,
            access_session_id=session.id,
            authority=session.authority,
            display_name=session.display_name,
        )

    def room_for_context(self, context: RoomAccessContext) -> Room:
        room = self.repository.get_room(context.room_id)
        if room is None:
            raise RoomNotFoundError(str(context.room_id))
        return _room_view(room)

    def heartbeat(self, context: RoomAccessContext) -> datetime:
        now = self.clock()
        if not self.repository.touch_access_session(context.access_session_id, now):
            raise RoomAccessRevokedError(str(context.access_session_id))
        return now


__all__ = [
    "RoomAccessDeniedError",
    "RoomAccessRevokedError",
    "RoomAccessThrottledError",
    "RoomNotFoundError",
    "RoomScopeMismatchError",
    "RoomService",
]
