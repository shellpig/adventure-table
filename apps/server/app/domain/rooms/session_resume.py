from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from app.domain.rooms.campaigns import Campaign, CampaignService
from app.domain.rooms.schemas import Room, StrictModel
from app.domain.rooms.seats import CampaignSeat, SeatService
from app.domain.rooms.sessions import (
    SessionNotFoundError,
    SessionParticipantSnapshot,
    SessionService,
    SessionSnapshot,
)
from app.persistence.rooms.repository import RoomRepository


class SessionResumeCharacterClass(StrictModel):
    class_ref: str
    level: int


class SessionResumeCharacterSummary(StrictModel):
    id: UUID
    name: str
    level: int
    classes: list[SessionResumeCharacterClass]
    version_no: int


class SessionResumeDTO(StrictModel):
    room_id: UUID
    campaign_id: UUID
    room: Room
    campaign: Campaign
    active_session: SessionSnapshot | None = None
    participants: list[SessionParticipantSnapshot]
    seats: list[CampaignSeat]
    active_characters: list[SessionResumeCharacterSummary]


class SessionResumeService:
    """Compose P2 Resume truth without inventing a second persistence snapshot."""

    def __init__(
        self,
        *,
        session_service: SessionService,
        room_repository: RoomRepository,
        campaign_service: CampaignService,
        seat_service: SeatService,
        character_repository: Any,
    ) -> None:
        self.session_service = session_service
        self.room_repository = room_repository
        self.campaign_service = campaign_service
        self.seat_service = seat_service
        self.character_repository = character_repository

    @staticmethod
    def _room(stored) -> Room:
        return Room(
            id=stored.id,
            code=stored.code,
            name=stored.name,
            active_campaign_id=stored.active_campaign_id,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )

    def _character_summary(self, character_id: UUID) -> SessionResumeCharacterSummary:
        character = self.character_repository.load_character(character_id)
        counts = Counter(character.build.class_progression)
        order = tuple(dict.fromkeys(character.build.class_progression))
        return SessionResumeCharacterSummary(
            id=character.id,
            name=character.name,
            level=character.build.character_level,
            classes=[
                SessionResumeCharacterClass(class_ref=class_ref, level=counts[class_ref])
                for class_ref in order
            ],
            version_no=character.version_no,
        )

    def resume(self, room_id: UUID, campaign_id: UUID) -> SessionResumeDTO:
        core = self.session_service.resume(room_id, campaign_id)
        stored_room = self.room_repository.get_room(room_id)
        if stored_room is None:
            raise SessionNotFoundError(room_id)
        room = self._room(stored_room)
        campaign = self.campaign_service.get_campaign(room_id, campaign_id)
        active_session = core.active_session
        if active_session is None:
            return SessionResumeDTO(
                room_id=room_id,
                campaign_id=campaign_id,
                room=room,
                campaign=campaign,
                active_session=None,
                participants=[],
                seats=[],
                active_characters=[],
            )

        participants = list(active_session.participants)
        participant_seat_ids = {participant.seat_id for participant in participants}
        seats = [
            seat
            for seat in self.seat_service.list_seats(room_id, campaign_id)
            if seat.id in participant_seat_ids
        ]

        character_ids: list[UUID] = []
        seen_character_ids: set[UUID] = set()
        for participant in participants:
            character_id = participant.active_character_id
            if character_id is None or character_id in seen_character_ids:
                continue
            seen_character_ids.add(character_id)
            character_ids.append(character_id)

        return SessionResumeDTO(
            room_id=room_id,
            campaign_id=campaign_id,
            room=room,
            campaign=campaign,
            active_session=active_session,
            participants=participants,
            seats=seats,
            active_characters=[
                self._character_summary(character_id) for character_id in character_ids
            ],
        )


__all__ = [
    "SessionResumeCharacterClass",
    "SessionResumeCharacterSummary",
    "SessionResumeDTO",
    "SessionResumeService",
]
