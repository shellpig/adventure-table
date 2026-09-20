from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from app.domain.rooms.schemas import StrictModel

RoomAssetKind = Literal["image", "source_document"]
RoomAssetVisibility = Literal["room", "dm_only"]


class RoomAsset(StrictModel):
    id: UUID
    room_id: UUID
    kind: RoomAssetKind
    original_filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    visibility: RoomAssetVisibility
    created_at: datetime


class RoomAssetCleanupReport(StrictModel):
    deleted: int
    failed: tuple[str, ...] = ()


class RoomAssetNotFoundError(Exception):
    pass


class RoomAssetForbiddenError(Exception):
    pass


class RoomAssetUnsupportedMediaTypeError(Exception):
    pass


class RoomAssetTooLargeError(Exception):
    pass


class RoomAssetVisibilityNotAllowedError(Exception):
    pass


class RoomAssetEmptyError(Exception):
    pass


class RoomAssetInUseError(Exception):
    pass


__all__ = [
    "RoomAsset",
    "RoomAssetCleanupReport",
    "RoomAssetEmptyError",
    "RoomAssetForbiddenError",
    "RoomAssetInUseError",
    "RoomAssetKind",
    "RoomAssetNotFoundError",
    "RoomAssetTooLargeError",
    "RoomAssetUnsupportedMediaTypeError",
    "RoomAssetVisibility",
    "RoomAssetVisibilityNotAllowedError",
]
