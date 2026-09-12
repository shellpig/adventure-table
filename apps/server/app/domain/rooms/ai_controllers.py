from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import Field, field_validator

from app.domain.rooms.ai_controller_tokens import (
    AIControllerTokenError,
    mint_ai_controller_token,
    parse_ai_controller_token,
    verify_ai_controller_secret,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext, StrictModel
from app.domain.rooms.table_events import TableActorContext, TableActorKind, TableEventService
from app.persistence.rooms.ai_controllers import (
    AIControllerGrantRepository,
    AIControllerGrantUnauthorizedPersistenceError,
    AIControllerHandoffPersistenceError,
    StoredAIControllerGrant,
    StoredAIControllerScope,
)


DEFAULT_PRE_SESSION_DM_TTL = timedelta(minutes=15)


class AIControllerError(RuntimeError):
    pass


class AIControllerUnauthorizedError(PermissionError):
    pass


class AIControllerHandoffError(AIControllerError):
    pass


class AIHandoffRequest(StrictModel):
    temporary_instruction: str | None = Field(default=None, max_length=2000)

    @field_validator("temporary_instruction")
    @classmethod
    def normalize_instruction(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        return value or None


class AIHumanReassignmentRequest(StrictModel):
    target_access_session_id: UUID


class AIControllerGrantView(StrictModel):
    grant_id: UUID
    seat_id: UUID
    role: str
    session_id: UUID | None = None
    generation: int
    token: str
    token_hint: str
    expires_at: datetime | None = None


class AIControllerAuthView(StrictModel):
    grant_id: UUID
    room_id: UUID
    campaign_id: UUID
    seat_id: UUID
    role: str
    session_id: UUID | None = None
    generation: int
    active_character_id: UUID | None = None
    is_current_dm: bool = False
    temporary_instruction: str | None = None


class AIControllerService:
    def __init__(
        self,
        repository: AIControllerGrantRepository,
        event_service: TableEventService,
    ) -> None:
        self.repository = repository
        self.event_service = event_service

    @staticmethod
    def _view(grant: StoredAIControllerGrant, plaintext: str) -> AIControllerGrantView:
        return AIControllerGrantView(
            grant_id=grant.id,
            seat_id=grant.seat_id,
            role=grant.role,
            session_id=grant.session_id,
            generation=grant.generation,
            token=plaintext,
            token_hint=grant.secret_prefix,
            expires_at=grant.pre_session_expires_at,
        )

    def let_ai_control_player(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        seat_id: UUID,
        context: RoomAccessContext,
        request: AIHandoffRequest,
    ) -> AIControllerGrantView:
        if context.room_id != room_id:
            raise AIControllerHandoffError("Room scope mismatch")
        minted = mint_ai_controller_token()
        result: list[StoredAIControllerGrant] = []

        def projection(connection, _event_id, _seq) -> None:
            result.append(
                self.repository.player_handoff_in_transaction(
                    connection,
                    grant_id=minted.grant_id,
                    room_id=room_id,
                    campaign_id=campaign_id,
                    session_id=session_id,
                    seat_id=seat_id,
                    caller_access_session_id=context.access_session_id,
                    secret_hash=minted.secret_hash,
                    secret_prefix=minted.display_hint,
                    temporary_instruction=request.temporary_instruction,
                )
            )

        try:
            self.event_service.repository.append(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                kind="controller.changed",
                acting_seat_id=seat_id,
                subject_seat_id=seat_id,
                subject_character_id=None,
                execution_mode="self",
                visibility="public",
                recipient_seat_ids=(),
                payload_version=1,
                payload={"controller_kind": "ai", "reason": "human_handoff"},
                idempotency_key=None,
                transaction_projection=projection,
            )
        except AIControllerHandoffPersistenceError as exc:
            raise AIControllerHandoffError(str(exc)) from exc
        if not result:
            raise RuntimeError("AI handoff projection did not produce a grant")
        if self.event_service.notifier is not None:
            self.event_service.notifier.notify(session_id)
        return self._view(result[0], minted.plaintext)

    def take_back_player(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        seat_id: UUID,
        context: RoomAccessContext,
    ) -> None:
        if context.room_id != room_id:
            raise AIControllerHandoffError("Room scope mismatch")

        def projection(connection, _event_id, _seq) -> None:
            self.repository.take_back_in_transaction(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                seat_id=seat_id,
                caller_access_session_id=context.access_session_id,
            )

        try:
            self.event_service.repository.append(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                kind="controller.changed",
                acting_seat_id=seat_id,
                subject_seat_id=seat_id,
                subject_character_id=None,
                execution_mode="self",
                visibility="public",
                recipient_seat_ids=(),
                payload_version=1,
                payload={"controller_kind": "human", "reason": "take_back"},
                idempotency_key=None,
                transaction_projection=projection,
            )
        except AIControllerHandoffPersistenceError as exc:
            raise AIControllerHandoffError(str(exc)) from exc
        if self.event_service.notifier is not None:
            self.event_service.notifier.notify(session_id)

    def administratively_reassign_player(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        session_id: UUID,
        seat_id: UUID,
        target_access_session_id: UUID,
        admin_context: RoomAccessContext,
    ) -> None:
        if admin_context.room_id != room_id:
            raise AIControllerHandoffError("Room scope mismatch")
        if admin_context.authority not in {
            RoomAccessAuthority.OWNER,
            RoomAccessAuthority.DM,
        }:
            raise AIControllerHandoffError(
                "Administrative reassignment requires active Owner or DM authority"
            )

        def projection(connection, _event_id, _seq) -> None:
            self.repository.admin_reassign_in_transaction(
                connection,
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                seat_id=seat_id,
                admin_access_session_id=admin_context.access_session_id,
                target_access_session_id=target_access_session_id,
            )

        try:
            self.event_service.repository.append(
                room_id=room_id,
                campaign_id=campaign_id,
                session_id=session_id,
                kind="controller.changed",
                acting_seat_id=None,
                subject_seat_id=seat_id,
                subject_character_id=None,
                execution_mode="dm_proxy",
                visibility="dm_only",
                recipient_seat_ids=(),
                payload_version=1,
                payload={
                    "controller_kind": "human",
                    "reason": "administrative_reassignment",
                    "admin_access_session_id": str(admin_context.access_session_id),
                    "target_access_session_id": str(target_access_session_id),
                },
                idempotency_key=None,
                transaction_projection=projection,
            )
        except AIControllerHandoffPersistenceError as exc:
            raise AIControllerHandoffError(str(exc)) from exc
        if self.event_service.notifier is not None:
            self.event_service.notifier.notify(session_id)

    def configure_pre_session_ai_dm(
        self,
        *,
        room_id: UUID,
        campaign_id: UUID,
        seat_id: UUID,
        ttl: timedelta = DEFAULT_PRE_SESSION_DM_TTL,
    ) -> AIControllerGrantView:
        now = datetime.now(timezone.utc)
        if ttl <= timedelta(0):
            raise AIControllerHandoffError("AI DM token TTL must be positive")
        minted = mint_ai_controller_token()
        try:
            grant = self.repository.mint_pre_session_dm(
                grant_id=minted.grant_id,
                room_id=room_id,
                campaign_id=campaign_id,
                seat_id=seat_id,
                secret_hash=minted.secret_hash,
                secret_prefix=minted.display_hint,
                expires_at=now + ttl,
                now=now,
            )
        except AIControllerHandoffPersistenceError as exc:
            raise AIControllerHandoffError(str(exc)) from exc
        return self._view(grant, minted.plaintext)

    def authenticate(self, token: str, *, touch: bool = False) -> AIControllerAuthView:
        try:
            parsed = parse_ai_controller_token(token)
        except AIControllerTokenError as exc:
            raise AIControllerUnauthorizedError("AI controller token is invalid") from exc
        grant = self.repository.get(parsed.grant_id)
        if grant is None or not verify_ai_controller_secret(parsed.secret, grant.secret_hash):
            raise AIControllerUnauthorizedError("AI controller token is invalid")
        return self.authenticate_grant(parsed.grant_id, touch=touch)

    def authenticate_grant(
        self,
        grant_id: UUID,
        *,
        touch: bool = False,
    ) -> AIControllerAuthView:
        try:
            scope = self.repository.resolve_current_scope(grant_id, touch=touch)
        except AIControllerGrantUnauthorizedPersistenceError as exc:
            raise AIControllerUnauthorizedError(str(exc)) from exc
        return self._auth_view(scope)

    @staticmethod
    def _auth_view(scope: StoredAIControllerScope) -> AIControllerAuthView:
        grant = scope.grant
        return AIControllerAuthView(
            grant_id=grant.id,
            room_id=grant.room_id,
            campaign_id=grant.campaign_id,
            seat_id=grant.seat_id,
            role=grant.role,
            session_id=scope.session_id,
            generation=grant.generation,
            active_character_id=scope.active_character_id,
            is_current_dm=scope.is_current_dm,
            temporary_instruction=grant.temporary_instruction,
        )

    @staticmethod
    def actor_from_auth(auth: AIControllerAuthView) -> TableActorContext:
        if auth.session_id is None:
            raise AIControllerUnauthorizedError(
                "pre-session AI DM grant is not a gameplay Session actor"
            )
        return TableActorContext(
            actor_kind=TableActorKind.AI,
            room_id=auth.room_id,
            campaign_id=auth.campaign_id,
            session_id=auth.session_id,
            seat_id=auth.seat_id,
            controlled_seat_ids=(auth.seat_id,),
            role=auth.role,
            is_current_dm=auth.is_current_dm,
            access_session_id=None,
            ai_controller_grant_id=auth.grant_id,
            grant_generation=auth.generation,
        )

    def resolve_actor(self, token: str, *, touch: bool = False) -> TableActorContext:
        return self.actor_from_auth(self.authenticate(token, touch=touch))


__all__ = [
    "AIControllerAuthView",
    "AIControllerError",
    "AIControllerGrantView",
    "AIControllerHandoffError",
    "AIControllerService",
    "AIControllerUnauthorizedError",
    "AIHandoffRequest",
    "AIHumanReassignmentRequest",
    "DEFAULT_PRE_SESSION_DM_TTL",
]
