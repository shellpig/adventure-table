from __future__ import annotations

from uuid import UUID

from app.content.registry import ContentRegistry
from app.domain.character.validation import CharacterValidationError, validate_build_references
from app.domain.character_builder.compiler import BuilderCompileResult, compile_builder_draft
from app.domain.character_builder.creation import (
    BuilderConfirmResult,
    BuilderReviewDTO,
    build_initial_character_state,
)
from app.domain.character_builder.schemas import (
    BuilderDraftCreateInput,
    BuilderDraftPatchInput,
    BuilderDraftPayload,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderMode,
    BuilderValidationResult,
    BuilderView,
)
from app.domain.character_builder.validation import make_validation_result
from app.domain.character_builder.view import build_builder_view
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository


class BuilderModeNotEnabledError(ValueError):
    def __init__(self, mode: BuilderMode) -> None:
        super().__init__(f"builder mode is not enabled yet: {mode.value}")
        self.mode = mode


class BuilderCannotConfirmError(ValueError):
    def __init__(self, validation: BuilderValidationResult) -> None:
        super().__init__("builder draft has blocking validation errors")
        self.validation = validation


class CharacterBuilderService:
    def __init__(
        self,
        repository: BuilderDraftRepository,
        registry: ContentRegistry,
        character_repository: CharacterRepository | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.character_repository = character_repository

    def create_draft(self, request: BuilderDraftCreateInput) -> BuilderView:
        if request.mode is not BuilderMode.CREATE:
            raise BuilderModeNotEnabledError(request.mode)
        draft = self.repository.create_draft(request)
        return build_builder_view(draft, self.registry)

    def list_create_drafts(self) -> tuple[BuilderView, ...]:
        return tuple(
            build_builder_view(draft, self.registry)
            for draft in self.repository.list_drafts(mode=BuilderMode.CREATE)
        )

    def get_draft(self, draft_id: UUID) -> BuilderView:
        draft = self.repository.load_draft(draft_id)
        return build_builder_view(draft, self.registry)

    def patch_draft(self, draft_id: UUID, request: BuilderDraftPatchInput) -> BuilderView:
        current = self.repository.load_draft(draft_id)
        payload_data = current.draft_payload.model_dump(mode="python")
        changes = request.draft_payload.model_dump(mode="python", exclude_unset=True)
        payload_data.update(changes)
        candidate = BuilderDraftPayload.model_validate(payload_data)
        updated = self.repository.update_draft_payload(
            draft_id,
            expected_revision=request.expected_revision,
            draft_payload=candidate,
        )
        return build_builder_view(updated, self.registry)

    def validate_draft(self, draft_id: UUID) -> BuilderValidationResult:
        review = self.review_draft(draft_id)
        return BuilderValidationResult(
            issues=review.issues,
            can_confirm=review.can_confirm,
            non_standard_count=review.non_standard_count,
        )

    def _compile_review(
        self,
        draft_id: UUID,
    ) -> tuple[BuilderCompileResult, BuilderReviewDTO]:
        draft = self.repository.load_draft(draft_id)
        compiled = compile_builder_draft(draft, self.registry)
        issues = list(compiled.validation.issues)
        state = None

        if compiled.validation.can_confirm and compiled.build_candidate is not None:
            try:
                validate_build_references(compiled.build_candidate, self.registry)
                state = build_initial_character_state(
                    compiled.build_candidate,
                    self.registry,
                    prepared_spells=compiled.initial_prepared_spells,
                )
            except (CharacterValidationError, ValueError) as exc:
                issues.append(
                    BuilderIssue(
                        code="final_character_validation_failed",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="draft_payload",
                        message=str(exc),
                    )
                )
        elif compiled.validation.can_confirm and compiled.build_candidate is None:
            issues.append(
                BuilderIssue(
                    code="build_candidate_missing",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft_payload",
                    message="The server could not compile a final CharacterBuild from this draft.",
                )
            )

        validation = make_validation_result(issues)
        review = BuilderReviewDTO(
            draft_id=draft.id,
            resolved_summary=compiled.resolved_summary,
            build_candidate=compiled.build_candidate,
            initial_state=state,
            starting_equipment=compiled.starting_equipment,
            issues=validation.issues,
            can_confirm=validation.can_confirm,
            non_standard_count=validation.non_standard_count,
        )
        return compiled, review

    def review_draft(self, draft_id: UUID) -> BuilderReviewDTO:
        return self._compile_review(draft_id)[1]

    def confirm_draft(self, draft_id: UUID) -> BuilderConfirmResult:
        if self.character_repository is None:
            raise RuntimeError("character repository is required for Confirm")

        confirmed_character_id = self.repository.confirmed_character_id(draft_id)
        if confirmed_character_id is not None:
            character = self.character_repository.load_character(confirmed_character_id)
            return BuilderConfirmResult(
                character_id=character.id,
                current_version_id=character.current_version_id,
                version_no=character.version_no,
                character_path=f"/characters/{character.id}",
            )

        compiled, review = self._compile_review(draft_id)
        if not review.can_confirm or compiled.build_candidate is None or review.initial_state is None:
            raise BuilderCannotConfirmError(
                BuilderValidationResult(
                    issues=review.issues,
                    can_confirm=review.can_confirm,
                    non_standard_count=review.non_standard_count,
                )
            )

        draft = self.repository.load_draft(draft_id)
        basic = draft.draft_payload.basic
        if basic is None or basic.name is None:
            raise BuilderCannotConfirmError(
                make_validation_result(
                    [
                        BuilderIssue(
                            code="missing_character_name",
                            severity=BuilderIssueSeverity.BLOCKING_ERROR,
                            path="draft_payload.basic.name",
                            message="Character name is required before Confirm.",
                        )
                    ]
                )
            )

        character = self.character_repository.create_character_from_builder_draft(
            draft_id=draft.id,
            expected_revision=draft.revision,
            name=basic.name,
            build=compiled.build_candidate,
            state=review.initial_state,
        )
        return BuilderConfirmResult(
            character_id=character.id,
            current_version_id=character.current_version_id,
            version_no=character.version_no,
            character_path=f"/characters/{character.id}",
        )

    def cancel_draft(self, draft_id: UUID) -> None:
        self.repository.delete_draft(draft_id)
