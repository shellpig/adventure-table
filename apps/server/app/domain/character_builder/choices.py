from __future__ import annotations

import re

from app.domain.character_builder.schemas import BuilderChoice, BuilderDraft


_CHOICE_PART = re.compile(r"[^a-z0-9:._-]+")


def deterministic_choice_id(*parts: str) -> str:
    normalized: list[str] = []
    for part in parts:
        value = _CHOICE_PART.sub("-", part.strip().lower()).strip("-")
        if not value:
            raise ValueError("choice id parts cannot be blank")
        normalized.append(value)
    return ":".join(normalized)


def build_foundation_choices(draft: BuilderDraft) -> tuple[BuilderChoice, ...]:
    payload = draft.draft_payload

    choices: list[BuilderChoice] = [
        BuilderChoice(
            choice_id=deterministic_choice_id("draft", "race-selection"),
            label="Race",
            required=True,
            choose_count=1,
            option_source="content:race",
            selected_option_ids=(
                (payload.race_selection.reference_id,)
                if payload.race_selection is not None
                else ()
            ),
            disabled_reason="Race choice resolution is implemented in P1-B.",
        ),
        BuilderChoice(
            choice_id=deterministic_choice_id("draft", "background-selection"),
            label="Background",
            required=True,
            choose_count=1,
            option_source="content:background",
            selected_option_ids=(
                (payload.background_selection.reference_id,)
                if payload.background_selection is not None
                else ()
            ),
            disabled_reason="Background choice resolution is implemented in P1-B.",
        ),
        BuilderChoice(
            choice_id=deterministic_choice_id("draft", "ability-generation"),
            label="Ability generation",
            required=True,
            choose_count=1,
            option_source="builder:ability-generation",
            disabled_reason="Ability generation is implemented in P1-B.",
        ),
    ]

    if payload.target_level is not None:
        for level in range(1, payload.target_level + 1):
            choices.append(
                BuilderChoice(
                    choice_id=deterministic_choice_id(
                        "level", str(level), "class-selection"
                    ),
                    label=f"Level {level} class",
                    required=True,
                    choose_count=1,
                    option_source="content:class",
                    disabled_reason="Class progression is implemented in P1-C.",
                )
            )

    known_ids = {choice.choice_id for choice in choices}
    for key in sorted(payload.choice_selections):
        selection = payload.choice_selections[key]
        if key in known_ids:
            continue
        choices.append(
            BuilderChoice(
                choice_id=selection.choice_id,
                label=selection.choice_id,
                source_ref=selection.source_ref,
                required=False,
                choose_count=len(selection.selected_option_ids),
                option_source="draft:selection",
                selected_option_ids=selection.selected_option_ids,
            )
        )

    return tuple(choices)
