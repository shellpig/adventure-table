from __future__ import annotations

from typing import Any

from fastapi import Request

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.errors import APIError
from app.api.rooms.table_event_wait import ProcessLocalTableEventNotifier
from app.domain.rooms.campaigns import CampaignService
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.exploration import ExplorationActionService, ExplorationStageService
from app.domain.rooms.pending_actions import PendingActionService
from app.domain.rooms.rolls import RollService
from app.domain.rooms.seats import SeatService
from app.domain.rooms.session_resume import SessionResumeService
from app.domain.rooms.sessions import SessionService
from app.domain.rooms.table_character_state import TableCharacterStateService
from app.domain.rooms.table_events import TableEventService
from app.domain.rooms.workspace import RoomCharacterWorkspaceService
from app.persistence.mcp.room_lifecycle import M04BSeatRepository, M04BSessionRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.exploration_messages import ExplorationMessageRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_character_state import TableCharacterStatePersistence
from app.persistence.rooms.p3c_pending import PendingActionRepository
from app.persistence.rooms.p3c_rolls import RollRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.session_resume import SessionResumeRepository
from app.persistence.rooms.table_runtime import TableEventRepository


class _HistoryGuardedCharacterRepository:
    """Web-only adapter that keeps multiplayer history out of Character Core."""

    def __init__(
        self,
        delegate: Any,
        campaigns: CampaignRepository,
        sessions: SessionLiveRepository,
    ) -> None:
        self._delegate = delegate
        self._campaigns = campaigns
        self._sessions = sessions

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def delete_character(self, character_id) -> None:
        if self._campaigns.character_is_referenced(character_id) or self._sessions.character_is_history_referenced(
            character_id
        ):
            raise APIError(
                409,
                "character_history_referenced",
                "Character is referenced by Campaign or Session history and cannot be permanently deleted",
            )
        self._delegate.delete_character(character_id)


def get_room_workspace_service(request: Request) -> RoomCharacterWorkspaceService:
    service = getattr(request.app.state, "room_workspace_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = RoomCharacterWorkspaceService(
            engine,
            get_content_registry(request),
        )
        service.character_repository = _HistoryGuardedCharacterRepository(
            service.character_repository,
            CampaignRepository(engine),
            SessionLiveRepository(engine),
        )
        request.app.state.room_workspace_service = service
    return service


def get_campaign_service(request: Request) -> CampaignService:
    service = getattr(request.app.state, "campaign_service", None)
    if service is None:
        service = CampaignService(CampaignRepository(get_database_engine(request)))
        request.app.state.campaign_service = service
    return service


def get_seat_service(request: Request) -> SeatService:
    service = getattr(request.app.state, "seat_service", None)
    if service is None:
        service = SeatService(M04BSeatRepository(get_database_engine(request)))
        request.app.state.seat_service = service
    return service


def get_table_event_notifier(request: Request) -> ProcessLocalTableEventNotifier:
    notifier = getattr(request.app.state, "table_event_notifier", None)
    if notifier is None:
        notifier = ProcessLocalTableEventNotifier()
        request.app.state.table_event_notifier = notifier
    return notifier


def get_table_event_service(request: Request) -> TableEventService:
    service = getattr(request.app.state, "table_event_service", None)
    if service is None:
        service = TableEventService(
            TableEventRepository(get_database_engine(request)),
            get_table_event_notifier(request),
        )
        request.app.state.table_event_service = service
    return service


def get_session_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = SessionService(
            M04BSessionRepository(engine),
            SessionLiveRepository(engine),
            get_table_event_service(request),
        )
        request.app.state.session_service = service
    return service


def get_exploration_stage_service(request: Request) -> ExplorationStageService:
    service = getattr(request.app.state, "exploration_stage_service", None)
    if service is None:
        service = ExplorationStageService(
            ExplorationRepository(get_database_engine(request)),
            get_table_event_service(request),
        )
        request.app.state.exploration_stage_service = service
    return service


def get_exploration_action_service(request: Request) -> ExplorationActionService:
    service = getattr(request.app.state, "exploration_action_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = ExplorationActionService(
            ExplorationSubjectRepository(engine),
            ExplorationMessageRepository(engine),
            get_table_event_service(request),
        )
        request.app.state.exploration_action_service = service
    return service


def get_roll_service(request: Request) -> RollService:
    service = getattr(request.app.state, "roll_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        character_repository = get_room_workspace_service(request).character_repository
        service = RollService(
            RollRepository(engine, event_service.repository),
            ExplorationSubjectRepository(engine),
            event_service,
            CharacterRollModifierResolver(
                character_repository,
                get_content_registry(request),
            ),
            registry=get_content_registry(request),
        )
        request.app.state.roll_service = service
    return service


def get_pending_action_service(request: Request) -> PendingActionService:
    service = getattr(request.app.state, "pending_action_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        roll_repository = get_roll_service(request).repository
        service = PendingActionService(
            PendingActionRepository(engine, event_service.repository),
            ExplorationSubjectRepository(engine),
            event_service,
            roll_repository,
        )
        request.app.state.pending_action_service = service
    return service


def get_table_character_state_service(request: Request) -> TableCharacterStateService:
    service = getattr(request.app.state, "table_character_state_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        service = TableCharacterStateService(
            TableCharacterStatePersistence(
                engine,
                get_content_registry(request),
                event_service.repository,
            ),
            ExplorationSubjectRepository(engine),
            event_service,
        )
        request.app.state.table_character_state_service = service
    return service


def get_session_resume_service(request: Request) -> SessionResumeService:
    service = getattr(request.app.state, "session_resume_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = SessionResumeService(
            session_service=get_session_service(request),
            room_repository=RoomRepository(engine),
            campaign_service=get_campaign_service(request),
            seat_service=get_seat_service(request),
            character_repository=get_room_workspace_service(request).character_repository,
            summary_repository=SessionResumeRepository(engine),
            table_event_service=get_table_event_service(request),
            stage_service=get_exploration_stage_service(request),
            roll_service=get_roll_service(request),
            pending_action_service=get_pending_action_service(request),
        )
        request.app.state.session_resume_service = service
    return service


__all__ = [
    "_HistoryGuardedCharacterRepository",
    "get_campaign_service",
    "get_exploration_action_service",
    "get_exploration_stage_service",
    "get_pending_action_service",
    "get_roll_service",
    "get_room_workspace_service",
    "get_seat_service",
    "get_session_resume_service",
    "get_session_service",
    "get_table_character_state_service",
    "get_table_event_notifier",
    "get_table_event_service",
]
