from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field

from app.domain.character.schemas import CharacterBuild
from app.domain.character_builder.m01j_subclasses import m01j_choice_id
from app.domain.character_builder.schemas import BuilderDraft


KNOWLEDGE_REF = "phb2014:subclass:knowledge"
SCOUT_REF = "xge:subclass:scout"
PURPLE_DRAGON_KNIGHT_REF = "scag:subclass:purple-dragon-knight"

KNOWLEDGE_SKILLS = frozenset(
    {
        "srd5.1:skill:arcana",
        "srd5.1:skill:history",
        "srd5.1:skill:nature",
        "srd5.1:skill:religion",
    }
)
SCOUT_SKILLS = (
    "srd5.1:skill:nature",
    "srd5.1:skill:survival",
)
PERSUASION_REF = "srd5.1:skill:persuasion"


@dataclass(frozen=True)
class _ExpertiseGrant:
    """One subclass feature that doubles the proficiency bonus for a skill.

    ``minimum_class_level`` is the level of the *parent class*, not the total
    character level: a Fighter 3 / Wizard 9 has not yet gained Royal Envoy.
    """

    minimum_class_level: int
    fixed_skills: tuple[str, ...] = ()
    choice_key: str | None = None
    choice_skills: frozenset[str] = field(default_factory=frozenset)


# Blessings of Knowledge is a 1st-level Knowledge Domain feature, Survivalist a
# 3rd-level Scout feature, and Royal Envoy a 7th-level Purple Dragon Knight one.
EXPERTISE_GRANTS: dict[str, _ExpertiseGrant] = {
    KNOWLEDGE_REF: _ExpertiseGrant(
        minimum_class_level=1,
        choice_key="knowledge-domain-skills",
        choice_skills=KNOWLEDGE_SKILLS,
    ),
    SCOUT_REF: _ExpertiseGrant(minimum_class_level=3, fixed_skills=SCOUT_SKILLS),
    PURPLE_DRAGON_KNIGHT_REF: _ExpertiseGrant(
        minimum_class_level=7, fixed_skills=(PERSUASION_REF,)
    ),
}


def _chosen_skills(
    draft: BuilderDraft, subclass_ref: str, grant: _ExpertiseGrant
) -> tuple[str, ...]:
    if grant.choice_key is None:
        return ()
    selection = draft.draft_payload.choice_selections.get(
        m01j_choice_id(subclass_ref, grant.choice_key)
    )
    if selection is None:
        return ()
    return tuple(ref for ref in selection.selected_option_ids if ref in grant.choice_skills)


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

    class_levels = Counter(build.class_progression)
    refs: list[str] = []

    for selection in build.subclasses:
        grant = EXPERTISE_GRANTS.get(selection.subclass_ref)
        if grant is None:
            continue
        if class_levels[selection.class_ref] < grant.minimum_class_level:
            continue
        refs.extend(grant.fixed_skills)
        refs.extend(_chosen_skills(draft, selection.subclass_ref, grant))

    expertise = tuple(
        ref
        for ref in dict.fromkeys(refs)
        if ref in build.skill_choices
    )
    return build.model_copy(update={"skill_expertise_refs": expertise})
