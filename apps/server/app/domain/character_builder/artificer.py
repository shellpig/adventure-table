from __future__ import annotations

from app.content.registry import ContentRegistry
from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder.choices import deterministic_choice_id
from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderChoiceOption,
    BuilderDraft,
    BuilderMode,
    BuilderOptionKind,
)
from app.domain.rules.artificer import ARTIFICER_REF, known_infusion_count


def _draft_artificer_level(draft: BuilderDraft) -> int:
    return sum(1 for level in draft.draft_payload.level_choices if level.class_ref == ARTIFICER_REF)


def _anchor_character_level(draft: BuilderDraft) -> int | None:
    levels = [
        level.character_level
        for level in draft.draft_payload.level_choices
        if level.class_ref == ARTIFICER_REF
    ]
    return max(levels) if levels else None


def infusion_choice_id(draft: BuilderDraft) -> str | None:
    anchor = _anchor_character_level(draft)
    if anchor is None or _draft_artificer_level(draft) < 2:
        return None
    return deterministic_choice_id("level", str(anchor), "artificer", "infusions-known")


def _level_up_infusion_choice_id(draft: BuilderDraft) -> str | None:
    """Anchor Level Up-only infusion work to the new character level.

    Normally this is the level where the character actually advances Artificer
    and gains a Known Infusion. It also covers pre-M01-H characters whose
    authoritative Build has no infusion_refs yet: even when another class is
    being advanced, the migration choice must use the target-level namespace so
    the Level Up patch guard permits the newly required choice without opening
    historical Build choices for editing.
    """

    if draft.mode is not BuilderMode.LEVEL_UP or _draft_artificer_level(draft) < 2:
        return None
    target_level = draft.draft_payload.target_level
    if target_level is None:
        return None
    return deterministic_choice_id(
        "level",
        str(target_level),
        "artificer",
        "infusions-known",
    )


def _infusion_options(
    registry: ContentRegistry,
    level: int,
    *,
    excluded_refs: set[str] | None = None,
) -> tuple[BuilderChoiceOption, ...]:
    excluded = excluded_refs or set()
    options: list[BuilderChoiceOption] = []
    for entry in registry.list_kind("infusion", source="tce"):
        if entry.key in excluded:
            continue
        minimum = entry.data.get("minimum_artificer_level")
        if not isinstance(minimum, int):
            # Content schema guarantees this; fail closed if an in-memory test
            # registry bypasses the normal pack loader.
            minimum = 20
        source_label = entry.source_label or entry.source
        disabled = minimum > level
        options.append(
            BuilderChoiceOption(
                option_id=entry.key,
                label=f"{entry.name} · {source_label}",
                kind=BuilderOptionKind.REFERENCE,
                reference_id=entry.key,
                disabled_reason=(
                    f"Requires Artificer level {minimum}." if disabled else None
                ),
                disabled_reason_code=(
                    "artificer_infusion_level_requirement" if disabled else None
                ),
                disabled_reason_params=(
                    {"minimum_artificer_level": minimum, "artificer_level": level}
                    if disabled
                    else {}
                ),
            )
        )
    return tuple(options)


def build_artificer_infusion_choices(
    draft: BuilderDraft,
    registry: ContentRegistry,
    *,
    base_build: CharacterBuild | None,
) -> tuple[BuilderChoice, ...]:
    level = _draft_artificer_level(draft)
    choice_id = infusion_choice_id(draft)
    if choice_id is None:
        return ()

    target_count = known_infusion_count(level)
    base_refs = base_build.infusion_refs if base_build is not None else ()
    choose_count = target_count
    excluded_refs: set[str] = set()
    if draft.mode is BuilderMode.LEVEL_UP:
        choose_count = max(0, target_count - len(base_refs))
        if choose_count == 0:
            return ()
        # Level Up may only add choices in the target-level namespace. This is
        # also the safe migration path for pre-H Artificers whose base Build has
        # no canonical infusion_refs yet, including multiclass Level Ups where
        # Artificer itself is not the class being advanced.
        level_up_choice_id = _level_up_infusion_choice_id(draft)
        if level_up_choice_id is None:
            return ()
        choice_id = level_up_choice_id
        # This choice is only the newly gained/migrated Known Infusions. If an
        # existing infusion remained selectable, the user could consume the
        # delta with a duplicate and leave the final immutable Build underfilled.
        excluded_refs = set(base_refs)

    selection = draft.draft_payload.choice_selections.get(choice_id)
    if selection is not None:
        selected = selection.selected_option_ids
    elif draft.mode in {BuilderMode.BUILD_EDIT, BuilderMode.CORRECTION} and base_build is not None:
        selected = base_refs
    else:
        selected = ()

    return (
        BuilderChoice(
            choice_id=choice_id,
            label="Artificer Infusions Known",
            source_ref="tce:feature:infuse-item",
            required=True,
            choose_count=choose_count,
            option_source="content:infusion",
            options=_infusion_options(registry, level, excluded_refs=excluded_refs),
            selected_option_ids=tuple(selected),
        ),
    )


def compile_artificer_infusion_refs(
    draft: BuilderDraft,
    choices: tuple[BuilderChoice, ...],
    *,
    base_build: CharacterBuild | None,
) -> tuple[str, ...]:
    if _draft_artificer_level(draft) < 2:
        return ()

    choice = next((item for item in choices if item.option_source == "content:infusion"), None)
    selected = choice.selected_option_ids if choice is not None else ()
    if draft.mode is BuilderMode.LEVEL_UP:
        base_refs = base_build.infusion_refs if base_build is not None else ()
        return tuple(dict.fromkeys((*base_refs, *selected)))
    if selected:
        return tuple(dict.fromkeys(selected))
    if base_build is not None and draft.mode in {BuilderMode.BUILD_EDIT, BuilderMode.CORRECTION}:
        return base_build.infusion_refs
    return ()
