from __future__ import annotations

from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder.m01j_subclasses import m01j_choice_id
from app.domain.character_builder.schemas import BuilderDraft


KNOWLEDGE_REF = "phb2014:subclass:knowledge"
SCOUT_REF = "xge:subclass:scout"
PURPLE_DRAGON_KNIGHT_REF = "scag:subclass:purple-dragon-knight"

KNOWLEDGE_SKILLS = {
    "srd5.1:skill:arcana",
    "srd5.1:skill:history",
    "srd5.1:skill:nature",
    "srd5.1:skill:religion",
}
SCOUT_SKILLS = (
    "srd5.1:skill:nature",
    "srd5.1:skill:survival",
)
PERSUASION_REF = "srd5.1:skill:persuasion"


def _active_subclasses(build: CharacterBuild) -> set[str]:
    return {selection.subclass_ref for selection in build.subclasses}


def _knowledge_expertise(draft: BuilderDraft) -> tuple[str, ...]:
    choice_id = m01j_choice_id(KNOWLEDGE_REF, "knowledge-domain-skills")
    selection = draft.draft_payload.choice_selections.get(choice_id)
    if selection is None:
        return ()
    return tuple(
        ref for ref in selection.selected_option_ids if ref in KNOWLEDGE_SKILLS
    )


def apply_m01j_skill_expertise(
    build: CharacterBuild,
    draft: BuilderDraft,
) -> CharacterBuild:
    """Persist expertise-like skill multipliers granted by M01-J subclasses.

    This intentionally covers subclass rules only. Core Bard/Rogue Expertise is
    outside M01-J and is not inferred here. Every emitted expertise ref must
    already be a skill proficiency on the final Build; CharacterBuild enforces
    that invariant as a second line of defense.
    """

    active = _active_subclasses(build)
    refs: list[str] = []

    if KNOWLEDGE_REF in active:
        refs.extend(_knowledge_expertise(draft))
    if SCOUT_REF in active:
        refs.extend(SCOUT_SKILLS)
    if PURPLE_DRAGON_KNIGHT_REF in active:
        refs.append(PERSUASION_REF)

    expertise = tuple(
        ref
        for ref in dict.fromkeys(refs)
        if ref in build.skill_choices
    )
    return build.model_copy(update={"skill_expertise_refs": expertise})
