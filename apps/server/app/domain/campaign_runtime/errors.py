from __future__ import annotations

from uuid import UUID

from app.domain.campaign_runtime.payloads import (
    CampaignRuntimeError,
)


class CampaignRuntimeAuthorityError(CampaignRuntimeError, PermissionError):
    """Raised when actor lacks required room/campaign management authority."""


class CampaignRuntimeNotFoundError(CampaignRuntimeError, LookupError):
    """Raised when room, campaign, or runtime entry is not found."""


class CampaignRuntimeConflictError(CampaignRuntimeError, RuntimeError):
    """Base exception for runtime conflicts."""


class CampaignRuntimeActiveSessionError(CampaignRuntimeConflictError):
    """Raised when management writes are attempted on a campaign with an active session."""


class CampaignRuntimeSessionNotActiveError(CampaignRuntimeConflictError):
    """Raised when active writes are attempted on a session that is not active."""


class CampaignRuntimeIdempotencyConflictError(CampaignRuntimeConflictError):
    """Raised when an idempotency key is reused with differing command or actor identity."""


class CampaignRuntimeRevisionConflictError(CampaignRuntimeConflictError):
    """Raised when expected revision does not match current entry revision."""

    def __init__(
        self,
        campaign_id: UUID,
        entry_id: UUID,
        expected_revision: int,
        current_revision: int,
        message: str | None = None,
    ) -> None:
        self.campaign_id = campaign_id
        self.entry_id = entry_id
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        detail = message or f"expected revision {expected_revision} but found {current_revision}"
        super().__init__(
            f"Runtime world entry {entry_id} revision conflict in campaign {campaign_id}: {detail}"
        )


class CampaignRuntimeArchivedError(CampaignRuntimeRevisionConflictError):
    """Raised when modifying or re-archiving an already-archived runtime entry."""

    def __init__(
        self,
        campaign_id: UUID,
        entry_id: UUID,
        expected_revision: int,
        current_revision: int,
    ) -> None:
        super().__init__(
            campaign_id=campaign_id,
            entry_id=entry_id,
            expected_revision=expected_revision,
            current_revision=current_revision,
            message="entry is already archived",
        )


class CampaignRuntimeValidationError(CampaignRuntimeError, ValueError):
    """Raised when business reference or payload invariants are violated."""
