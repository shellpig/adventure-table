from __future__ import annotations

from collections import Counter
from typing import Any
from uuid import UUID

from app.domain.character.schemas import CharacterBuild
from app.domain.rooms.campaigns import Campaign, CampaignService
from app.domain.rooms.exploration import ExplorationStageService, StageState
from app.domain.rooms.schemas import (
    Room,
    RoomAccessAuthority,
    RoomAccessContext,
    StrictModel,
)
from app.domain.rooms.seats import CampaignSeat, SeatService
from app.domain.rooms.sessions import (
    SessionNotFoundError,
    SessionParticipantSnapshot,
    SessionService,
    SessionSnapshot,
)
from app.domain.rooms.table_events import (
    TableEventActorUnauthorizedError,
    TableEventNotFoundError,
    TableEventPage,
    TableEventService,
    TableRuntimeCursor,
)
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.session_resume import SessionResumeRepository


RECENT_EVENT_WINDOW = 50


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
    # Same caller identity the Lobby reports, mirrored here because Resume is the
    # only Session-scoped read that survives the Room switching active Campaign.
    caller_access_session_id: UUID | None = None
    # P3-A adds only a projection of canonical event truth. These fields are not
    # a second persisted Session snapshot and remain absent for non-participants.
    table_runtime: TableRuntimeCursor | None = None
    recent_events: TableEventPage | None = None
    # P3-B Main Stage is canonical persisted Session state, projected here only
    # for authorized Session participants alongside the P3-A event projection.
    stage: StageState | None = None


class SessionResumeService:
    """Compose canonical P2/P3 Session truth without a second persisted snapshot."""

    def __init__(
        self,
        *,
        session_service: SessionService,
        room_repository: RoomRepository,
        campaign_service: CampaignService,
        seat_service: SeatService,
        character_repository: Any,
        summary_repository: SessionResumeRepository | None = None,
        table_event_service: TableEventService | None = None,
        stage_service: ExplorationStageService | None = None,
    ) -> None:
        self.session_service = session_service
        self.room_repository = room_repository
        self.campaign_service = campaign_service
        self.seat_service = seat_service
        self.character_repository = character_repository
        self.summary_repository = summary_repository
        self.table_event_service = table_event_service
        self.stage_service = stage_service

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

    @staticmethod
    def _build_summary(
        *,
        character_id: UUID,
        name: str,
        version_no: int,
        build: CharacterBuild,
    ) -> SessionResumeCharacterSummary:
        counts = Counter(build.class_progression)
        order = tuple(dict.fromkeys(build.class_progression))
        return SessionResumeCharacterSummary(
            id=character_id,
            name=name,
            level=build.character_level,
            classes=[
                SessionResumeCharacterClass(class_ref=class_ref, level=counts[class_ref])
                for class_ref in order
            ],
            version_no=version_no,
        )

    def _character_summaries(
        self,
        character_ids: list[UUID],
    ) -> list[SessionResumeCharacterSummary]:
        if not character_ids:
            return []
        if self.summary_repository is not None:
            rows = self.summary_repository.load_character_summaries(character_ids)
            return [
                self._build_summary(
                    character_id=row.id,
                    name=row.name,
                    version_no=row.version_no,
                    build=CharacterBuild.model_validate(row.build_payload),
                )
                for row in rows
            ]

        # Compatibility fallback for tests/custom adapters that predate P3-A.
        # Production Web dependency wiring always supplies summary_repository,
        # which makes this one batch query rather than one Character load/Seat.
        result: list[SessionResumeCharacterSummary] = []
        for character_id in character_ids:
            character = self.character_repository.load_character(character_id)
            result.append(
                self._build_summary(
                    character_id=character.id,
                    name=character.name,
                    version_no=character.version_no,
                    build=character.build,
                )
            )
        return result

    def _table_projection(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        caller_access_session_id: UUID | None,
    ) -> tuple[TableRuntimeCursor | None, TableEventPage | None, StageState | None]:
        if self.table_event_service is None or caller_access_session_id is None:
            return None, None, None

        # TableEventRepository resolves the authoritative Human access-session
        # binding. The RoomAccessAuthority value is intentionally not used to
        # grant gameplay scope; P3-D will replace this adapter with the shared
        # Human/AI actor resolver without changing the projection service.
        context = RoomAccessContext(
            room_id=room_id,
            access_session_id=caller_access_session_id,
            authority=RoomAccessAuthority.MEMBER,
        )
        try:
            actor = self.table_event_service.resolve_human_actor(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                context=context,
            )
            runtime = self.table_event_service.current_cursor(actor)
            after_seq = max(0, runtime.last_event_seq - RECENT_EVENT_WINDOW)
            recent = self.table_event_service.list_after(
                actor,
                after_seq=after_seq,
                limit=RECENT_EVENT_WINDOW,
            )
            stage = self.stage_service.get_stage(actor) if self.stage_service is not None else None
        except (TableEventNotFoundError, TableEventActorUnauthorizedError):
            # Room members who are not Session participants may still use the P2
            # Resume endpoint, but they receive no P3 projection. If controller
            # authority changes while these independently revalidated reads are
            # composed, fail the whole P3 projection closed instead of turning an
            # otherwise valid P2 Resume into a transient 500.
            return None, None, None
        return runtime, recent, stage

    def resume(
        self,
        room_id: UUID,
        campaign_id: UUID,
        *,
        caller_access_session_id: UUID | None = None,
    ) -> SessionResumeDTO:
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
                caller_access_session_id=caller_access_session_id,
            )

        participants = list(active_session.participants)
        participant_seat_ids = {participant.seat_id for participant in participants}
        seats = [
            seat
            for seat in self.seat_service.list_seats(
                room_id,
                campaign_id,
                include_archived=True,
            )
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

        table_runtime, recent_events, stage = self._table_projection(
            room_id=room_id,
            campaign_id=campaign_id,
            session_id=active_session.id,
            caller_access_session_id=caller_access_session_id,
        )

        return SessionResumeDTO(
            room_id=room_id,
            campaign_id=campaign_id,
            room=room,
            campaign=campaign,
            active_session=active_session,
            participants=participants,
            seats=seats,
            active_characters=self._character_summaries(character_ids),
            caller_access_session_id=caller_access_session_id,
            table_runtime=table_runtime,
            recent_events=recent_events,
            stage=stage,
        )


__all__ = [
    "RECENT_EVENT_WINDOW",
    "SessionResumeCharacterClass",
    "SessionResumeCharacterSummary",
    "SessionResumeDTO",
    "SessionResumeService",
]
