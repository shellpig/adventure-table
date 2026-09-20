from __future__ import annotations

from datetime import datetime, timezone
import hashlib
from typing import BinaryIO, cast
from uuid import UUID, uuid4

from app.domain.room_assets.schemas import (
    RoomAsset,
    RoomAssetEmptyError,
    RoomAssetForbiddenError,
    RoomAssetInUseError,
    RoomAssetKind,
    RoomAssetNotFoundError,
    RoomAssetTooLargeError,
    RoomAssetUnsupportedMediaTypeError,
    RoomAssetVisibility,
    RoomAssetVisibilityNotAllowedError,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.room_assets.repository import RoomAssetRepository, StoredRoomAsset
from app.persistence.room_assets.storage import FilesystemAssetStorage

IMAGE_MIME_TYPES: dict[str, str] = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
}

SOURCE_DOCUMENT_MIME_TYPES: dict[str, str] = {
    "text/plain": ".txt",
    "text/markdown": ".md",
    "application/pdf": ".pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": ".docx",
}


def _visible(stored: StoredRoomAsset, context: RoomAccessContext) -> bool:
    if context.authority in (RoomAccessAuthority.OWNER, RoomAccessAuthority.DM):
        return True
    return stored.visibility == "room"


def _to_view(stored: StoredRoomAsset) -> RoomAsset:
    return RoomAsset(
        id=stored.id,
        room_id=stored.room_id,
        kind=cast(RoomAssetKind, stored.kind),
        original_filename=stored.original_filename,
        mime_type=stored.mime_type,
        size_bytes=stored.size_bytes,
        sha256=stored.sha256,
        visibility=cast(RoomAssetVisibility, stored.visibility),
        created_at=stored.created_at,
    )


class RoomAssetService:
    def __init__(
        self,
        repository: RoomAssetRepository,
        storage: FilesystemAssetStorage,
        *,
        max_image_bytes: int,
        max_source_document_bytes: int,
    ) -> None:
        self.repository = repository
        self.storage = storage
        self.max_image_bytes = max_image_bytes
        self.max_source_document_bytes = max_source_document_bytes

    def create(
        self,
        context: RoomAccessContext,
        *,
        room_id: UUID,
        kind: RoomAssetKind,
        filename: str,
        mime_type: str,
        data: bytes,
        visibility: RoomAssetVisibility = "room",
    ) -> RoomAsset:
        if context.room_id != room_id:
            raise RoomAssetNotFoundError(f"Room {room_id} not found")
        if context.authority is RoomAccessAuthority.MEMBER:
            raise RoomAssetForbiddenError("Owner or DM authority is required")
        if kind == "source_document" and visibility != "dm_only":
            raise RoomAssetVisibilityNotAllowedError("source_document must have visibility dm_only")

        if kind == "image":
            if mime_type not in IMAGE_MIME_TYPES:
                raise RoomAssetUnsupportedMediaTypeError(f"Unsupported image media type: {mime_type}")
            ext = IMAGE_MIME_TYPES[mime_type]
            limit = self.max_image_bytes
        elif kind == "source_document":
            if mime_type not in SOURCE_DOCUMENT_MIME_TYPES:
                raise RoomAssetUnsupportedMediaTypeError(f"Unsupported source document media type: {mime_type}")
            ext = SOURCE_DOCUMENT_MIME_TYPES[mime_type]
            limit = self.max_source_document_bytes
        else:
            raise RoomAssetUnsupportedMediaTypeError(f"Unsupported asset kind: {kind}")

        if len(data) == 0:
            raise RoomAssetEmptyError("Asset data cannot be empty")
        if len(data) > limit:
            raise RoomAssetTooLargeError(f"Asset size {len(data)} exceeds limit of {limit} bytes")

        sha256 = hashlib.sha256(data).hexdigest()
        asset_id = uuid4()
        storage_key = f"{room_id}/{asset_id}{ext}"
        now = datetime.now(timezone.utc)

        stored = StoredRoomAsset(
            id=asset_id,
            room_id=room_id,
            kind=kind,
            storage_key=storage_key,
            original_filename=filename,
            mime_type=mime_type,
            size_bytes=len(data),
            sha256=sha256,
            visibility=visibility,
            created_at=now,
        )

        try:
            with self.repository.engine.begin() as connection:
                self.repository.insert_in_transaction(connection, stored)
                self.storage.write(storage_key, data)
        except BaseException:
            self.storage.delete(storage_key)
            raise

        return _to_view(stored)

    def get(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        asset_id: UUID,
    ) -> RoomAsset:
        if context.room_id != room_id:
            raise RoomAssetNotFoundError(f"Room {room_id} not found")
        stored = self.repository.get(room_id, asset_id)
        if stored is None or not _visible(stored, context):
            raise RoomAssetNotFoundError(f"Room asset {asset_id} not found")
        return _to_view(stored)

    def list(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        kind: RoomAssetKind | None = None,
    ) -> list[RoomAsset]:
        if context.room_id != room_id:
            raise RoomAssetNotFoundError(f"Room {room_id} not found")
        stored_list = self.repository.list_for_room(room_id, kind=kind)
        return [_to_view(stored) for stored in stored_list if _visible(stored, context)]

    def open_content(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        asset_id: UUID,
    ) -> tuple[RoomAsset, BinaryIO]:
        if context.room_id != room_id:
            raise RoomAssetNotFoundError(f"Room {room_id} not found")
        stored = self.repository.get(room_id, asset_id)
        if stored is None or not _visible(stored, context):
            raise RoomAssetNotFoundError(f"Room asset {asset_id} not found")
        handle = self.storage.open(stored.storage_key)
        return _to_view(stored), handle

    def delete(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        asset_id: UUID,
    ) -> None:
        if context.room_id != room_id:
            raise RoomAssetNotFoundError(f"Room {room_id} not found")
        if context.authority is RoomAccessAuthority.MEMBER:
            raise RoomAssetForbiddenError("Owner or DM authority is required")
        stored = self.repository.get(room_id, asset_id)
        if stored is None:
            raise RoomAssetNotFoundError(f"Room asset {asset_id} not found")
        if self.repository.is_referenced(asset_id):
            raise RoomAssetInUseError(f"Room asset {asset_id} is referenced by an adventure entry")
        deleted = self.repository.delete(room_id, asset_id)
        if deleted is not None:
            self.storage.delete(deleted.storage_key)


__all__ = [
    "IMAGE_MIME_TYPES",
    "RoomAssetService",
    "SOURCE_DOCUMENT_MIME_TYPES",
]
