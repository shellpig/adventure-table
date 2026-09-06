from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.domain.rooms.schemas import (
    Room,
    RoomAccessAuthority,
    RoomAccessContext,
    RoomAccessGrant,
)

if TYPE_CHECKING:
    from app.domain.rooms.service import RoomService
    from app.domain.rooms.workspace import RoomCharacterWorkspaceService, RoomWorkspaceScopeError


def __getattr__(name: str) -> Any:
    """Load service-layer exports lazily so schema imports stay cycle-free.

    Persistence modules import ``app.domain.rooms.schemas`` directly. Python
    initializes this package before that submodule, so eagerly importing Room
    services here would bounce back into persistence while it is only partially
    initialized. Keeping the convenience exports lazy preserves the public
    package surface without coupling schema imports to service construction.
    """

    if name == "RoomService":
        from app.domain.rooms.service import RoomService

        return RoomService
    if name in {"RoomCharacterWorkspaceService", "RoomWorkspaceScopeError"}:
        from app.domain.rooms.workspace import RoomCharacterWorkspaceService, RoomWorkspaceScopeError

        return {
            "RoomCharacterWorkspaceService": RoomCharacterWorkspaceService,
            "RoomWorkspaceScopeError": RoomWorkspaceScopeError,
        }[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "Room",
    "RoomAccessAuthority",
    "RoomAccessContext",
    "RoomAccessGrant",
    "RoomCharacterWorkspaceService",
    "RoomService",
    "RoomWorkspaceScopeError",
]
