from __future__ import annotations

from dataclasses import replace
from uuid import UUID

from app.content.registry import ContentRegistry
from app.domain.character.validation import CharacterValidationError, validate_build_references
from app.domain.character_builder.compiler import BuilderCompileResult
from app.domain.character_builder.m01i_compiler import compile_builder_draft
from app.domain.character_builder.creation import (
    BuilderConfirmResult,
    BuilderReviewDTO,
    build_initial_character_state,
    build_review_derived_stats,
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
from app.persistence.characters import CharacterRepository, StaleBuildVersionError


class BuilderModeNotEnabledError(ValueError):
    def __init__(self, mode: BuilderMode) -> None:
        super().__init__(f"builder mode is not enabled: {mode.value}")
        self.mode = mode


class BuilderCannotConfirmError(ValueError):
    def __init__(self, validation: BuilderValidationResult) -> None:
        super().__init__("builder draft has blocking validation errors")
        self.validation = validation


M01J_CHOICE_PREFIX = "m01-j:"


def _is_cumulative_subclass_choice(choice_id: str) -> bool:
    """Is this an M01-J subclass choice that keeps growing as the class levels?"""

    return choice_id.startswith(M01J_CHOICE_PREFIX)


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

    @staticmethod
    def _version_contract_issues(
        draft: BuilderDraft,
        base_build,
        compiled: BuilderCompileResult,
    ) -> tuple[BuilderIssue, ...]:
        if draft.mode is BuilderMode.CREATE:
            return ()
        expected_level = (
            base_build.character_level + 1
            if draft.mode is BuilderMode.LEVEL_UP
            else base_build.character_level
        )
        issues: list[BuilderIssue] = []
        if draft.draft_payload.target_level != expected_level:
            issues.append(
                BuilderIssue(
                    code="invalid_version_target_level",
                    severity=BuilderIssueSeverity.BLOCKING_ERROR,
                    path="draft_payload.target_level",
                    message=(
                        f"{draft.mode.value} must target Character Level {expected_level}; "
                        f"got {draft.draft_payload.target_level}."
                    ),
                )
            )

        if draft.mode is BuilderMode.LEVEL_UP:
            historical = draft.draft_payload.level_choices[: base_build.character_level]
            if tuple(level.class_ref for level in historical) != base_build.class_progression:
                issues.append(
                    BuilderIssue(
                        code="level_up_historical_progression_changed",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="draft_payload.level_choices",
                        message="Level Up cannot rewrite class choices from the base Build.",
                    )
                )
            if tuple(level.hp_base_gain for level in historical) != base_build.hp_progression:
                issues.append(
                    BuilderIssue(
                        code="level_up_historical_hp_changed",
                        severity=BuilderIssueSeverity.BLOCKING_ERROR,
                        path="draft_payload.level_choices",
                        message="Level Up cannot rewrite historical HP progression from the base Build.",
                    )
                )

            candidate = compiled.build_candidate
            if candidate is not None:
                group_provenance_unchanged = (
                    not base_build.race_variant_group_selections
                    or candidate.race_variant_group_selections
                    == base_build.race_variant_group_selections
                )
                immutable_origin = (
                    candidate.race_ref == base_build.race_ref
                    and candidate.race_variant_ref == base_build.race_variant_ref
                    and group_provenance_unchanged
                    and candidate.subrace_ref == base_build.subrace_ref
                    and candidate.background_ref == base_build.background_ref
                    and candidate.alignment_ref == base_build.alignment_ref
                )
                if not immutable_origin:
                    issues.append(
                        BuilderIssue(
                            code="level_up_origin_changed",
                            severity=BuilderIssueSeverity.BLOCKING_ERROR,
                            path="draft_payload",
                            message="Level Up cannot rewrite race/ancestry/background/alignment; use Build Edit or Correction.",
                        )
                    )
                if candidate.starting_equipment != base_build.starting_equipment:
                    issues.append(
                        BuilderIssue(
                            code="level_up_starting_equipment_changed",
                            severity=BuilderIssueSeverity.BLOCKING_ERROR,
                            path="build.starting_equipment",
                            message="Level Up must preserve immutable starting-equipment provenance.",
                        )
                    )
                if candidate.numeric_overrides != base_build.numeric_overrides:
                    issues.append(
                        BuilderIssue(
                            code="level_up_numeric_override_changed",
                            severity=BuilderIssueSeverity.BLOCKING_ERROR,
                            path="draft_payload.numeric_overrides",
                            message="Numeric Overrides are not a Level Up choice; use Build Edit or Correction.",
                        )
                    )
        return tuple(issues)

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
        extra_issues: list[BuilderIssue] = []
        if base_build is not None:
            extra_issues.extend(self._version_contract_issues(draft, base_build, compiled))
        if stale_issue is not None:
            extra_issues.append(stale_issue)
        if extra_issues:
            validation = make_validation_result((*compiled.validation.issues, *extra_issues))
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

    def _guard_level_up_patch(
        self,
        current: BuilderDraft,
        changes: dict[str, object],
    ) -> None:
        if current.mode is not BuilderMode.LEVEL_UP:
            return
        if current.character_id is None or current.base_version_id is None:
            raise ValueError("level_up draft is missing its base version")
        base_build = self._require_character_repository().load_build_version(
            current.character_id,
            current.base_version_id,
        )
        immutable_fields = {
            "target_level",
            "race_selection",
            "race_variant_selection",
            "subrace_selection",
            "background_selection",
            "alignment_selection",
            "ability_generation",
            "starting_equipment_choices",
            "roleplay_profile",
            "numeric_overrides",
            "initial_state_seed",
        }
        current_payload = current.draft_payload.model_dump(mode="python")
        for field in immutable_fields.intersection(changes):
            if changes[field] != current_payload[field]:
                raise ValueError(
                    f"level_up cannot modify historical field {field}; use build_edit or correction"
                )

        if "level_choices" in changes:
            proposed_levels = changes["level_choices"]
            if not isinstance(proposed_levels, (list, tuple)):
                raise ValueError("level_choices must be an ordered list")
            current_prefix = current.draft_payload.level_choices[: base_build.character_level]
            proposed_prefix = tuple(proposed_levels[: base_build.character_level])
            normalized_prefix = tuple(
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in current_prefix
            )
            normalized_proposed = tuple(
                item.model_dump(mode="python") if hasattr(item, "model_dump") else item
                for item in proposed_prefix
            )
            if normalized_proposed != normalized_prefix:
                raise ValueError("level_up cannot modify historical level choices")

        if "choice_selections" in changes:
            proposed = changes["choice_selections"]
            if not isinstance(proposed, dict):
                raise ValueError("choice_selections must be an object")
            current_selections = current.draft_payload.choice_selections
            target_level = base_build.character_level + 1
            current_compiled = self._compile(current)
            allowed_new_feat_choice_ids = {
                choice.choice_id
                for choice in current_compiled.choices
                if (choice.option_source or "").startswith("content:feat:")
            }
            for choice_id, old_selection in current_selections.items():
                if choice_id.startswith(f"level:{target_level}:"):
                    continue
                proposed_selection = proposed.get(choice_id)
                old_dump = old_selection.model_dump(mode="python")
                proposed_dump = (
                    proposed_selection.model_dump(mode="python")
                    if hasattr(proposed_selection, "model_dump")
                    else proposed_selection
                )
                if _is_cumulative_subclass_choice(choice_id):
                    old_options = set(old_dump.get("selected_option_ids") or ())
                    proposed_options = set(
                        (proposed_dump or {}).get("selected_option_ids") or ()
                    )
                    if not old_options <= proposed_options:
                        raise ValueError(
                            f"level_up cannot drop earlier selections from {choice_id}"
                        )
                    continue
                if proposed_dump != old_dump:
                    raise ValueError(
                        f"level_up cannot modify historical choice {choice_id}"
                    )
            for choice_id in proposed:
                if (
                    choice_id not in current_selections
                    and not choice_id.startswith(f"level:{target_level}:")
                    and not _is_cumulative_subclass_choice(choice_id)
                    and choice_id not in allowed_new_feat_choice_ids
                ):
                    raise ValueError(
                        f"level_up cannot add non-level-up choice {choice_id}"
                    )

    def patch_draft(self, draft_id: UUID, request: BuilderDraftPatchInput) -> BuilderView:
        current = self.repository.load_draft(draft_id)
        payload_data = current.draft_payload.model_dump(mode="python")
        changes = request.draft_payload.model_dump(mode="python", exclude_unset=True)
        self._guard_level_up_patch(current, changes)
        if "roleplay_profile" in changes:
            proposed_profile = changes["roleplay_profile"]
            if proposed_profile is None:
                changes["roleplay_profile"] = {}
            elif not isinstance(proposed_profile, dict):
                raise ValueError("roleplay_profile must be an object")
            else:
                existing_profile = payload_data.get("roleplay_profile")
                merged_profile = (
                    dict(existing_profile) if isinstance(existing_profile, dict) else {}
                )
                merged_profile.update(proposed_profile)
                changes["roleplay_profile"] = merged_profile
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
        derived_stats = (
            build_review_derived_stats(compiled.build_candidate, self.registry)
            if compiled.build_candidate is not None
            else None
        )

        if compiled.validation.can_confirm and compiled.build_candidate is not None:
            try:
                validate_build_references(compiled.build_candidate, self.registry)
                if draft.mode is BuilderMode.CREATE:
                    initial_state = build_initial_character_state(
                        compiled.build_candidate,
                        self.registry,
                        prepared_spells=compiled.initial_prepared_spells,
                        initial_state_seed=draft.draft_payload.initial_state_seed,
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
            derived_stats=derived_stats,
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

        confirmed_character_id, confirmed_version_id = self.repository.confirmed_result(draft_id)
        if confirmed_character_id is not None:
            if confirmed_version_id is None:
                character = character_repository.load_character(confirmed_character_id)
                return BuilderConfirmResult(
                    character_id=character.id,
                    current_version_id=character.current_version_id,
                    version_no=character.version_no,
                    character_path=f"/characters/{character.id}",
                )
            confirmed_version = next(
                (
                    version
                    for version in character_repository.list_versions(confirmed_character_id)
                    if version.id == confirmed_version_id
                ),
                None,
            )
            if confirmed_version is None:
                raise RuntimeError(
                    f"confirmed builder version is missing: {confirmed_version_id}"
                )
            return BuilderConfirmResult(
                character_id=confirmed_character_id,
                current_version_id=confirmed_version_id,
                version_no=confirmed_version.version_no,
                character_path=f"/characters/{confirmed_character_id}",
            )

        draft_snapshot = self.repository.load_draft(draft_id)
        if draft_snapshot.mode is not BuilderMode.CREATE:
            if draft_snapshot.character_id is None or draft_snapshot.base_version_id is None:
                raise ValueError("versioned draft is missing its base version")
            current = character_repository.load_character(draft_snapshot.character_id)
            if current.current_version_id != draft_snapshot.base_version_id:
                raise StaleBuildVersionError(
                    current.id,
                    draft_snapshot.base_version_id,
                    current.current_version_id,
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