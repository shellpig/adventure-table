from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class RoomAccessAuthority(StrEnum):
    MEMBER = "member"
    DM = "dm"
    OWNER = "owner"


class Room(StrictModel):
    id: UUID
    code: str
    name: str
    active_campaign_id: UUID | None = None
    created_at: datetime
    updated_at: datetime


class RoomAccessSession(StrictModel):
    id: UUID
    room_id: UUID
    authority: RoomAccessAuthority
    display_name: str | None = None
    created_at: datetime
    last_seen_at: datetime
    revoked_at: datetime | None = None


class RoomAccessContext(StrictModel):
    room_id: UUID
    access_session_id: UUID
    authority: RoomAccessAuthority
    display_name: str | None = None


class CreateRoomRequest(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    password: str = Field(min_length=6, max_length=128)
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("room name cannot be blank")
        return normalized

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class EnterRoomRequest(StrictModel):
    code: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    elevated_key: str | None = Field(default=None, min_length=16, max_length=256)
    display_name: str | None = Field(default=None, max_length=100)

    @field_validator("display_name")
    @classmethod
    def normalize_display_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        return normalized or None


class RoomAccessGrant(StrictModel):
    room: Room
    authority: RoomAccessAuthority
    access_session_id: UUID
    access_token: str
    owner_key: str | None = None
    dm_key: str | None = None


class HeartbeatResponse(StrictModel):
    ok: bool = True
    server_time: datetime


__all__ = [
    "CreateRoomRequest",
    "EnterRoomRequest",
    "HeartbeatResponse",
    "Room",
    "RoomAccessAuthority",
    "RoomAccessContext",
    "RoomAccessGrant",
    "RoomAccessSession",
]
