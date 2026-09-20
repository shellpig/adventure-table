from __future__ import annotations

from typing import Any

from fastapi import Request

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.errors import APIError
from app.api.rooms.table_event_wait import ProcessLocalTableEventNotifier
from app.config import settings
from app.domain.adventures.attachments import CampaignAdventureService
from app.domain.adventures.service import AdventureService
from app.domain.campaign_runtime.service import CampaignRuntimeService
from app.domain.combat.adjudication_service import CombatAdjudicationService
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import CombatAttackService
from app.domain.combat.concentration import CombatConcentrationService
from app.domain.combat.core_rolls import CombatCoreRollService
from app.domain.combat.initiative import CombatInitiativeService
from app.domain.combat.lifecycle import CombatService
from app.domain.combat.monster_instances import MonsterInstanceService
from app.domain.combat.order import CombatOrderService
from app.domain.combat.reaction_service import CombatReactionService
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.domain.combat.semantic_hp import CombatResolutionService
from app.domain.combat.special_attacks import CombatSpecialAttackService
from app.domain.combat.spell_service import CombatSpellService
from app.domain.room_assets.service import RoomAssetService
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
from app.paths import resolve_asset_root
from app.persistence.adventures.repository import (
    AdventureRepository,
    CampaignAdventureLinkRepository,
)
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.combat.concentration import CombatConcentrationRepository
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.initiative import CombatInitiativeRepository
from app.persistence.combat.lifecycle import CombatRepository
from app.persistence.combat.order import CombatOrderRepository
from app.persistence.combat.reactions import CombatReactionRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.resolution import CombatResolutionRepository
from app.persistence.combat.special_attacks import SpecialAttackRepository
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.mcp.room_lifecycle import M04BSeatRepository, M04BSessionRepository
from app.persistence.room_assets.repository import RoomAssetRepository
from app.persistence.room_assets.storage import FilesystemAssetStorage
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.exploration_messages import ExplorationMessageRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_character_state import TableCharacterStatePersistence
from app.persistence.rooms.p3c_pending import PendingActionRepository
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.session_live import SessionLiveRepository
from app.persistence.rooms.session_resume import SessionResumeRepository
from app.persistence.rooms.table_runtime import TableEventRepository


class _HistoryGuardedCharacterRepository:
    """Web-only adapter that keeps multiplayer history out of Character Core."""

    def __init__(self, delegate: Any, campaigns: CampaignRepository, sessions: SessionLiveRepository) -> None:
        self._delegate = delegate
        self._campaigns = campaigns
        self._sessions = sessions

    def __getattr__(self, name: str) -> Any:
        return getattr(self._delegate, name)

    def delete_character(self, character_id) -> None:
        if self._campaigns.character_is_referenced(character_id) or self._sessions.character_is_history_referenced(character_id):
            raise APIError(409, "character_history_referenced", "Character is referenced by Campaign or Session history and cannot be permanently deleted")
        self._delegate.delete_character(character_id)


def get_room_workspace_service(request: Request) -> RoomCharacterWorkspaceService:
    service = getattr(request.app.state, "room_workspace_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = RoomCharacterWorkspaceService(engine, get_content_registry(request))
        service.character_repository = _HistoryGuardedCharacterRepository(
            service.character_repository, CampaignRepository(engine), SessionLiveRepository(engine)
        )
        request.app.state.room_workspace_service = service
    return service


def get_campaign_service(request: Request) -> CampaignService:
    service = getattr(request.app.state, "campaign_service", None)
    if service is None:
        service = CampaignService(CampaignRepository(get_database_engine(request)))
        request.app.state.campaign_service = service
    return service


def get_room_asset_service(request: Request) -> RoomAssetService:
    # Starlette State has no membership test; the AttributeError is the "not built yet" signal.
    try:
        return request.app.state.room_asset_service
    except AttributeError:
        pass
    service = RoomAssetService(
        RoomAssetRepository(get_database_engine(request)),
        FilesystemAssetStorage(resolve_asset_root()),
        max_image_bytes=settings.asset_max_image_bytes,
        max_source_document_bytes=settings.asset_max_source_document_bytes,
    )
    request.app.state.room_asset_service = service
    return service


def get_adventure_service(request: Request) -> AdventureService:
    # Starlette State has no membership test; the AttributeError is the "not built yet" signal.
    try:
        return request.app.state.adventure_service
    except AttributeError:
        pass
    engine = get_database_engine(request)
    service = AdventureService(
        AdventureRepository(engine),
        RoomAssetRepository(engine),
    )
    request.app.state.adventure_service = service
    return service


def get_campaign_adventure_service(request: Request) -> CampaignAdventureService:
    # Starlette State has no membership test; the AttributeError is the "not built yet" signal.
    try:
        return request.app.state.campaign_adventure_service
    except AttributeError:
        pass
    engine = get_database_engine(request)
    service = CampaignAdventureService(
        CampaignAdventureLinkRepository(engine),
        AdventureRepository(engine),
        CampaignRepository(engine),
    )
    request.app.state.campaign_adventure_service = service
    return service


def get_campaign_runtime_service(request: Request) -> CampaignRuntimeService:
    # Starlette State has no membership test; the AttributeError is the "not built yet" signal.
    try:
        return request.app.state.campaign_runtime_service
    except AttributeError:
        pass
    service = CampaignRuntimeService(
        get_database_engine(request),
        get_table_event_service(request),
    )
    request.app.state.campaign_runtime_service = service
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
        service = TableEventService(TableEventRepository(get_database_engine(request)), get_table_event_notifier(request))
        request.app.state.table_event_service = service
    return service


def get_session_service(request: Request) -> SessionService:
    service = getattr(request.app.state, "session_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = SessionService(M04BSessionRepository(engine), SessionLiveRepository(engine), get_table_event_service(request))
        request.app.state.session_service = service
    return service


def get_exploration_stage_service(request: Request) -> ExplorationStageService:
    service = getattr(request.app.state, "exploration_stage_service", None)
    if service is None:
        service = ExplorationStageService(ExplorationRepository(get_database_engine(request)), get_table_event_service(request))
        request.app.state.exploration_stage_service = service
    return service


def get_exploration_action_service(request: Request) -> ExplorationActionService:
    service = getattr(request.app.state, "exploration_action_service", None)
    if service is None:
        engine = get_database_engine(request)
        service = ExplorationActionService(ExplorationSubjectRepository(engine), ExplorationMessageRepository(engine), get_table_event_service(request))
        request.app.state.exploration_action_service = service
    return service


def get_roll_service(request: Request) -> RollService:
    service = getattr(request.app.state, "roll_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        character_repository = get_room_workspace_service(request).character_repository
        service = RollService(
            CombatAwareRollRepository(engine, event_service.repository),
            ExplorationSubjectRepository(engine),
            event_service,
            CharacterRollModifierResolver(character_repository, get_content_registry(request)),
            registry=get_content_registry(request),
        )
        request.app.state.roll_service = service
    return service


def get_pending_action_service(request: Request) -> PendingActionService:
    service = getattr(request.app.state, "pending_action_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        service = PendingActionService(
            PendingActionRepository(engine, event_service.repository),
            ExplorationSubjectRepository(engine),
            event_service,
            get_roll_service(request).repository,
        )
        request.app.state.pending_action_service = service
    return service


def get_table_character_state_service(request: Request) -> TableCharacterStateService:
    service = getattr(request.app.state, "table_character_state_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        service = TableCharacterStateService(
            TableCharacterStatePersistence(engine, get_content_registry(request), event_service.repository),
            ExplorationSubjectRepository(engine),
            event_service,
        )
        request.app.state.table_character_state_service = service
    return service


def get_combat_service(request: Request) -> CombatService:
    service = getattr(request.app.state, "combat_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        service = CombatService(
            CombatRepository(engine, event_service.repository),
            event_service,
            get_room_workspace_service(request).character_repository,
            MonsterRepository(engine),
            get_content_registry(request),
        )
        request.app.state.combat_service = service
    return service


def get_combat_resolution_service(request: Request) -> CombatResolutionService:
    service = getattr(request.app.state, "combat_resolution_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        combat_service = get_combat_service(request)
        service = CombatResolutionService(
            CombatResolutionRepository(engine, event_service.repository), combat_service.repository, combat_service, event_service
        )
        request.app.state.combat_resolution_service = service
    return service


def get_combat_attack_service(request: Request) -> CombatAttackService:
    service = getattr(request.app.state, "combat_attack_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        combat_service = get_combat_service(request)
        service = CombatAttackService(
            CombatAttackRepository(engine, event_service.repository),
            CombatAdjudicationRepository(engine, event_service.repository),
            combat_service.repository,
            combat_service,
            AttackDefinitionResolver(
                get_room_workspace_service(request).character_repository,
                combat_service.monster_repository,
                get_content_registry(request),
            ),
            get_roll_service(request),
            event_service,
        )
        request.app.state.combat_attack_service = service
    return service


def get_combat_adjudication_service(request: Request) -> CombatAdjudicationService:
    service = getattr(request.app.state, "combat_adjudication_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        combat_service = get_combat_service(request)
        service = CombatAdjudicationService(
            repository=CombatAdjudicationRepository(engine, event_service.repository),
            combat_repository=combat_service.repository,
            combat_service=combat_service,
            table_event_service=event_service,
        )
        request.app.state.combat_adjudication_service = service
    return service


def get_combat_concentration_service(request: Request) -> CombatConcentrationService:
    service = getattr(request.app.state, "combat_concentration_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        combat_service = get_combat_service(request)
        service = CombatConcentrationService(
            CombatConcentrationRepository(engine, event_service.repository),
            combat_service.repository,
            combat_service.monster_repository,
            get_roll_service(request),
            event_service,
        )
        request.app.state.combat_concentration_service = service
    return service


def get_combat_core_roll_service(request: Request) -> CombatCoreRollService:
    service = getattr(request.app.state, "combat_core_roll_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        combat_service = get_combat_service(request)
        service = CombatCoreRollService(
            CombatCoreRollRepository(engine, event_service.repository),
            combat_service.repository,
            combat_service,
            combat_service.monster_repository,
            get_roll_service(request),
            event_service,
            concentration_service=get_combat_concentration_service(request),
        )
        request.app.state.combat_core_roll_service = service
    return service


def get_combat_special_attack_service(request: Request) -> CombatSpecialAttackService:
    service = getattr(request.app.state, "combat_special_attack_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        combat_service = get_combat_service(request)
        service = CombatSpecialAttackService(
            SpecialAttackRepository(engine, event_service.repository),
            CombatCoreRollRepository(engine, event_service.repository),
            combat_service.repository,
            combat_service,
            get_room_workspace_service(request).character_repository,
            combat_service.monster_repository,
            get_content_registry(request),
            get_roll_service(request),
            event_service,
        )
        request.app.state.combat_special_attack_service = service
    return service


def get_combat_initiative_service(request: Request) -> CombatInitiativeService:
    service = getattr(request.app.state, "combat_initiative_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        combat_service = get_combat_service(request)
        service = CombatInitiativeService(
            CombatInitiativeRepository(engine, event_service.repository),
            combat_service.repository,
            combat_service,
            combat_service.monster_repository,
            get_roll_service(request),
            event_service,
        )
        request.app.state.combat_initiative_service = service
    return service


def get_combat_order_service(request: Request) -> CombatOrderService:
    service = getattr(request.app.state, "combat_order_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        service = CombatOrderService(CombatOrderRepository(engine, event_service.repository), get_combat_service(request), event_service)
        request.app.state.combat_order_service = service
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


def get_combat_reaction_service(request: Request) -> CombatReactionService:
    service = getattr(request.app.state, "combat_reaction_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        combat_service = get_combat_service(request)
        service = CombatReactionService(
            repository=CombatReactionRepository(engine, event_service.repository),
            combat_repository=combat_service.repository,
            combat_service=combat_service,
            table_event_service=event_service,
        )
        request.app.state.combat_reaction_service = service
    return service


def get_combat_spell_service(request: Request) -> CombatSpellService:
    service = getattr(request.app.state, "combat_spell_service", None)
    if service is None:
        engine = get_database_engine(request)
        event_service = get_table_event_service(request)
        combat_service = get_combat_service(request)
        service = CombatSpellService(
            repository=CombatSpellRepository(engine, event_service.repository),
            combat_repository=combat_service.repository,
            combat_service=combat_service,
            table_event_service=event_service,
            monster_repository=combat_service.monster_repository,
            character_repository=get_room_workspace_service(request).character_repository,
            roll_service=get_roll_service(request),
            registry=get_content_registry(request),
        )
        request.app.state.combat_spell_service = service
    return service


def get_monster_instance_service(request: Request) -> MonsterInstanceService:
    service = getattr(request.app.state, "monster_instance_service", None)
    if service is None:
        combat_service = get_combat_service(request)
        service = MonsterInstanceService(
            monster_repository=combat_service.monster_repository,
            content_registry=get_content_registry(request),
            table_event_service=get_table_event_service(request),
        )
        request.app.state.monster_instance_service = service
    return service


__all__ = [
    "_HistoryGuardedCharacterRepository",
    "get_adventure_service",
    "get_campaign_adventure_service",
    "get_campaign_service",
    "get_combat_adjudication_service",
    "get_combat_attack_service",
    "get_combat_concentration_service",
    "get_combat_core_roll_service",
    "get_combat_initiative_service",
    "get_combat_order_service",
    "get_combat_reaction_service",
    "get_combat_resolution_service",
    "get_combat_service",
    "get_combat_special_attack_service",
    "get_combat_spell_service",
    "get_exploration_action_service",
    "get_exploration_stage_service",
    "get_monster_instance_service",
    "get_pending_action_service",
    "get_roll_service",
    "get_room_asset_service",
    "get_room_workspace_service",
    "get_seat_service",
    "get_session_resume_service",
    "get_session_service",
    "get_table_character_state_service",
    "get_table_event_notifier",
    "get_table_event_service",
]

