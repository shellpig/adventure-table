from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from app.content.registry import ContentRegistry
from app.domain.character.validation import CharacterValidationError, validate_build_references
from app.domain.character_builder.compiler import BuilderCompileResult, compile_builder_draft
from app.domain.character_builder.creation import (
    BuilderConfirmResult,
    BuilderReviewDTO,
    build_initial_character_state,
)
from app.domain.character_builder.reconciliation import reconcile_character_state
from app.domain.character_builder.schemas import (
    BuilderDraft,
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
from app.domain.character_builder.versions import (
    CharacterVersionKind,
    seed_version_draft_payload,
)
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository


class BuilderModeNotEnabledError(ValueError):
    def __init__(self, mode: BuilderMode) -> None:
        super().__init__(f"builder mode is not enabled: {mode.value}")
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

    def _require_character_repository(self) -> CharacterRepository:
        if self.character_repository is None:
            raise RuntimeError("character repository is required for this builder workflow")
        return self.character_repository

    def _compile(self, draft: BuilderDraft) -> BuilderCompileResult:
        base_build = None
        stale_issue: BuilderIssue | None = None
        if draft.mode is not BuilderMode.CREATE:
            character_repository = self._require_character_repository()
            if draft.character_id is None or draft.base_version_id is None:
                raise ValueError("versioned draft requires character_id and base_version_id")
            base_build = character_repository.load_build_version(
                draft.character_id,
                draft.base_version_id,
            )
            current = character_repository.load_character(draft.character_id)
            if current.current_version_id != draft.base_version_id:
                stale_issue = BuilderIssue(
                    code="stale_build_version",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft.base_version_id",
                    message=(
                        "This draft was based on an older Build version. Open a new "
                        "draft from the current character version before Confirm."
                    ),
                    related_refs=(str(draft.base_version_id), str(current.current_version_id)),
                )

        compiled = compile_builder_draft(
            draft,
            self.registry,
            base_build=base_build,
        )
        if stale_issue is not None:
            validation = make_validation_result((*compiled.validation.issues, stale_issue))
            compiled = replace(compiled, validation=validation)
        return compiled

    @staticmethod
    def _view(draft: BuilderDraft, compiled: BuilderCompileResult) -> BuilderView:
        return BuilderView(
            draft=draft,
            resolved_summary=compiled.resolved_summary,
            choices=compiled.choices,
            validation=compiled.validation,
        )

    def create_draft(self, request: BuilderDraftCreateInput) -> BuilderView:
        # Non-create drafts must be initialized from the authoritative current
        # character so callers cannot choose an arbitrary base_version_id or fake
        # historical provenance. Use create_version_draft() for those modes.
        if request.mode is not BuilderMode.CREATE:
            raise BuilderModeNotEnabledError(request.mode)
        draft = self.repository.create_draft(request)
        return self._view(draft, self._compile(draft))

    def create_version_draft(
        self,
        character_id: UUID,
        mode: BuilderMode,
    ) -> BuilderView:
        if mode is BuilderMode.CREATE:
            raise ValueError("create_version_draft requires a versioned builder mode")
        character_repository = self._require_character_repository()
        character = character_repository.load_character(character_id)
        source_payload = self.repository.load_payload_for_confirmed_version(
            character.id,
            character.current_version_id,
        )
        payload = seed_version_draft_payload(
            character,
            self.registry,
            mode=mode,
            source_payload=source_payload,
            state=character.state,
        )
        request = BuilderDraftCreateInput(
            mode=mode,
            character_id=character.id,
            base_version_id=character.current_version_id,
            draft_payload=payload,
        )
        draft = self.repository.create_draft(request)
        return self._view(draft, self._compile(draft))

    def list_create_drafts(self) -> tuple[BuilderView, ...]:
        return tuple(
            self._view(draft, self._compile(draft))
            for draft in self.repository.list_drafts(mode=BuilderMode.CREATE)
        )

    def list_character_drafts(self, character_id: UUID) -> tuple[BuilderView, ...]:
        return tuple(
            self._view(draft, self._compile(draft))
            for draft in self.repository.list_drafts(character_id=character_id)
        )

    def get_draft(self, draft_id: UUID) -> BuilderView:
        draft = self.repository.load_draft(draft_id)
        return self._view(draft, self._compile(draft))

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
        return self._view(updated, self._compile(updated))

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
    ) -> tuple[BuilderDraft, BuilderCompileResult, BuilderReviewDTO]:
        draft = self.repository.load_draft(draft_id)
        compiled = self._compile(draft)
        issues = list(compiled.validation.issues)
        initial_state = None
        reconciliation = None

        if compiled.validation.can_confirm and compiled.build_candidate is not None:
            try:
                validate_build_references(compiled.build_candidate, self.registry)
                if draft.mode is BuilderMode.CREATE:
                    initial_state = build_initial_character_state(
                        compiled.build_candidate,
                        self.registry,
                        prepared_spells=compiled.initial_prepared_spells,
                    )
                else:
                    character_repository = self._require_character_repository()
                    if draft.character_id is None or draft.base_version_id is None:
                        raise ValueError("versioned draft is missing its base character")
                    current = character_repository.load_character(draft.character_id)
                    if current.current_version_id == draft.base_version_id:
                        base_build = character_repository.load_build_version(
                            draft.character_id,
                            draft.base_version_id,
                        )
                        reconciliation = reconcile_character_state(
                            base_build,
                            current.state,
                            compiled.build_candidate,
                            self.registry,
                        )
                        issues.extend(reconciliation.warnings)
                        issues.extend(reconciliation.blocking_issues)
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
            initial_state=initial_state,
            reconciliation=reconciliation,
            starting_equipment=compiled.starting_equipment,
            issues=validation.issues,
            can_confirm=validation.can_confirm,
            non_standard_count=validation.non_standard_count,
        )
        return draft, compiled, review

    def review_draft(self, draft_id: UUID) -> BuilderReviewDTO:
        return self._compile_review(draft_id)[2]

    def confirm_draft(self, draft_id: UUID) -> BuilderConfirmResult:
        character_repository = self._require_character_repository()

        confirmed_character_id, _confirmed_version_id = self.repository.confirmed_result(draft_id)
        if confirmed_character_id is not None:
            character = character_repository.load_character(confirmed_character_id)
            return BuilderConfirmResult(
                character_id=character.id,
                current_version_id=character.current_version_id,
                version_no=character.version_no,
                character_path=f"/characters/{character.id}",
            )

        draft, compiled, review = self._compile_review(draft_id)
        if not review.can_confirm or compiled.build_candidate is None:
            raise BuilderCannotConfirmError(
                BuilderValidationResult(
                    issues=review.issues,
                    can_confirm=review.can_confirm,
                    non_standard_count=review.non_standard_count,
                )
            )

        if draft.mode is BuilderMode.CREATE:
            if review.initial_state is None:
                raise BuilderCannotConfirmError(
                    make_validation_result(
                        [
                            BuilderIssue(
                                code="initial_state_missing",
                                severity=BuilderIssueSeverity.BLOCKING_ERROR,
                                path="draft_payload",
                                message="The server could not build initial Current State.",
                            )
                        ]
                    )
                )
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
            character = character_repository.create_character_from_builder_draft(
                draft_id=draft.id,
                expected_revision=draft.revision,
                name=basic.name,
                build=compiled.build_candidate,
                state=review.initial_state,
            )
        else:
            kind_by_mode = {
                BuilderMode.LEVEL_UP: CharacterVersionKind.LEVEL_UP,
                BuilderMode.BUILD_EDIT: CharacterVersionKind.BUILD_EDIT,
                BuilderMode.CORRECTION: CharacterVersionKind.CORRECTION,
            }
            version_kind = kind_by_mode[draft.mode]
            character, _ = character_repository.create_build_version_from_builder_draft(
                draft_id=draft.id,
                expected_revision=draft.revision,
                new_build=compiled.build_candidate,
                version_kind=version_kind,
            )

        return BuilderConfirmResult(
            character_id=character.id,
            current_version_id=character.current_version_id,
            version_no=character.version_no,
            character_path=f"/characters/{character.id}",
        )

    def cancel_draft(self, draft_id: UUID) -> None:
        self.repository.delete_draft(draft_id)
