from __future__ import annotations

from uuid import UUID

from app.content.registry import ContentRegistry
from app.domain.rooms.rolls import (
    RollInputInvalidError,
    RollRequestType,
)
from app.domain.rules.abilities import (
    ability_modifier,
    effective_ability_score,
    normalize_ability_name,
)
from app.domain.rules.skills import saving_throw_modifier, skill_modifier
from app.persistence.characters import CharacterRepository


class CharacterRollModifierResolver:
    """Resolve formal P3-C modifiers from the canonical Character Build.

    P3-C owns no duplicate 5e arithmetic. Ability, Skill, and Saving Throw
    requests delegate to the Character Core rule helpers so numeric overrides,
    proficiency, expertise, and future Character-rule maintenance remain SSOT.
    """

    def __init__(
        self,
        character_repository: CharacterRepository,
        registry: ContentRegistry,
    ) -> None:
        self.character_repository = character_repository
        self.registry = registry

    def modifier_for(
        self,
        *,
        character_id: UUID,
        request_type: RollRequestType,
        ability_ref: str | None,
        skill_ref: str | None,
    ) -> int:
        build = self.character_repository.load_character(character_id).build

        try:
            if request_type is RollRequestType.ABILITY:
                if ability_ref is None:
                    raise RollInputInvalidError("ability roll requires ability_ref")
                ability_name = normalize_ability_name(ability_ref)
                return ability_modifier(effective_ability_score(build, ability_name))

            if request_type is RollRequestType.SKILL:
                if skill_ref is None:
                    raise RollInputInvalidError("skill roll requires skill_ref")
                return skill_modifier(build, skill_ref, self.registry)

            if request_type is RollRequestType.SAVING_THROW:
                if ability_ref is None:
                    raise RollInputInvalidError("saving throw requires ability_ref")
                ability_name = normalize_ability_name(ability_ref)
                return saving_throw_modifier(build, ability_name)

            if request_type is RollRequestType.OTHER:
                # Generic formal rolls have no Character-derived base modifier.
                # Any DM-authored adjustment remains the RollRequest's audited
                # flat_adjustment rather than client-supplied hidden arithmetic.
                return 0
        except RollInputInvalidError:
            raise
        except (KeyError, ValueError) as exc:
            raise RollInputInvalidError(str(exc)) from exc

        raise RollInputInvalidError(f"unsupported roll request type: {request_type}")


__all__ = ["CharacterRollModifierResolver"]
