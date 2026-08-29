from __future__ import annotations

from uuid import UUID

from app.content.registry import ContentRegistry
from app.domain.character_builder.schemas import (
    BuilderDraftCreateInput,
    BuilderDraftPatchInput,
    BuilderDraftPayload,
    BuilderMode,
    BuilderValidationResult,
    BuilderView,
)
from app.domain.character_builder.view import build_builder_view
from app.persistence.builder_drafts import BuilderDraftRepository


class BuilderModeNotEnabledError(ValueError):
    def __init__(self, mode: BuilderMode) -> None:
        super().__init__(f"builder mode is not enabled in P1-A: {mode.value}")
        self.mode = mode


class CharacterBuilderService:
    def __init__(
        self,
        repository: BuilderDraftRepository,
        registry: ContentRegistry,
    ) -> None:
        self.repository = repository
        self.registry = registry

    def create_draft(self, request: BuilderDraftCreateInput) -> BuilderView:
        if request.mode is not BuilderMode.CREATE:
            raise BuilderModeNotEnabledError(request.mode)
        draft = self.repository.create_draft(request)
        return build_builder_view(draft, self.registry)

    def get_draft(self, draft_id: UUID) -> BuilderView:
        draft = self.repository.load_draft(draft_id)
        return build_builder_view(draft, self.registry)

    def patch_draft(
        self,
        draft_id: UUID,
        request: BuilderDraftPatchInput,
    ) -> BuilderView:
        current = self.repository.load_draft(draft_id)
        payload_data = current.draft_payload.model_dump(mode="python")
        changes = request.draft_payload.model_dump(
            mode="python",
            exclude_unset=True,
        )
        payload_data.update(changes)
        candidate = BuilderDraftPayload.model_validate(payload_data)
        updated = self.repository.update_draft_payload(
            draft_id,
            expected_revision=request.expected_revision,
            draft_payload=candidate,
        )
        return build_builder_view(updated, self.registry)

    def validate_draft(self, draft_id: UUID) -> BuilderValidationResult:
        return self.get_draft(draft_id).validation

    def cancel_draft(self, draft_id: UUID) -> None:
        self.repository.delete_draft(draft_id)
