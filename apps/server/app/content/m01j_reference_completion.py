from __future__ import annotations

from copy import deepcopy
from typing import Any

from app.content import m01j_reference_fixes as _fixes
from app.content.registry import ContentRegistry


# Final source-id correction and small permanent-grant additions found during
# the second static rules pass. Keeping these edits in one layer makes the
# generic parser remain source-layout agnostic while the normalized runtime is
# explicit and machine-verifiable.


def _merge_fixed_grant(subclass_ref: str, field: str, *refs: str) -> None:
    current = deepcopy(_fixes.FIXED_GRANTS.get(subclass_ref, {}))
    values = list(current.get(field, ()))
    values.extend(refs)
    current[field] = tuple(dict.fromkeys(values))
    _fixes.FIXED_GRANTS[subclass_ref] = current


def _append_grant_choice(subclass_ref: str, choice: dict[str, Any]) -> None:
    current = list(_fixes.GRANT_CHOICES.get(subclass_ref, ()))
    key = choice.get("choice_key")
    if not any(isinstance(item, dict) and item.get("choice_key") == key for item in current):
        current.append(choice)
    _fixes.GRANT_CHOICES[subclass_ref] = tuple(current)


def _append_fixed_spell(
    subclass_ref: str,
    *,
    minimum_class_level: int,
    spell_ref: str,
    access_type: str = "granted",
) -> None:
    current = list(_fixes.FIXED_SPELLS.get(subclass_ref, ()))
    identity = (minimum_class_level, spell_ref, access_type)
    known = {
        (
            int(item.get("minimum_class_level", 0)),
            str(item.get("spell_ref", "")),
            str(item.get("access_type", "")),
        )
        for item in current
        if isinstance(item, dict)
    }
    if identity not in known:
        current.append(
            {
                "minimum_class_level": minimum_class_level,
                "spell_ref": spell_ref,
                "access_type": access_type,
            }
        )
    _fixes.FIXED_SPELLS[subclass_ref] = tuple(current)


def _prepare_completion_constants() -> None:
    # Circle of Spores is in TCE for this M01 baseline. The initial static pass
    # used its pre-TCE publication lineage accidentally; normalize to the
    # canonical M01 source identity before applying any metadata.
    stale_spores = _fixes.FIXED_SPELLS.pop("xge:subclass:spores", ())
    if stale_spores:
        current = list(_fixes.FIXED_SPELLS.get("tce:subclass:spores", ()))
        current.extend(stale_spores)
        _fixes.FIXED_SPELLS["tce:subclass:spores"] = tuple(current)

    _merge_fixed_grant("scag:subclass:arcana", "skills", "srd5.1:skill:arcana")

    _append_grant_choice(
        "tce:subclass:fey-wanderer",
        {
            "choice_key": "fey-wanderer-skill",
            "label": "Otherworldly Glamour — skill",
            "minimum_class_level": 3,
            "choose_total": 1,
            "grant_target": "skill",
            "option_refs": (
                "srd5.1:skill:deception",
                "srd5.1:skill:performance",
                "srd5.1:skill:persuasion",
            ),
        },
    )

    _append_fixed_spell(
        "tce:subclass:swarmkeeper",
        minimum_class_level=3,
        spell_ref="srd5.1:spell:mage-hand",
    )
    _append_fixed_spell(
        "phb2014:subclass:illusion",
        minimum_class_level=2,
        spell_ref="srd5.1:spell:minor-illusion",
    )


def apply_m01j_reference_completion(registry: ContentRegistry) -> ContentRegistry:
    _prepare_completion_constants()
    return _fixes.apply_m01j_reference_fixes(registry)
