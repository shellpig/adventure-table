from __future__ import annotations

from app.content.m01j_reference_content import SPELL_INDEX_ALIASES
from app.content.registry import ContentValidationError


# The temporary subclass reference documents use these Chinese titles for the
# Divine Soul affinity spells. They point at existing canonical SRD identities;
# this layer is name reconciliation only and never creates or overrides rules.
DIVINE_SOUL_SPELL_INDEX_ALIASES: dict[str, str] = {
    "治療傷勢": "cure-wounds",
    "造成傷勢": "inflict-wounds",
    "祝福術": "bless",
    "災禍術": "bane",
    "防護善惡": "protection-from-evil-and-good",
}


def install_m01j_spell_aliases() -> None:
    """Install verified reference-title aliases before M01-J document parsing."""

    conflicts = {
        name: (SPELL_INDEX_ALIASES[name], index)
        for name, index in DIVINE_SOUL_SPELL_INDEX_ALIASES.items()
        if name in SPELL_INDEX_ALIASES and SPELL_INDEX_ALIASES[name] != index
    }
    if conflicts:
        raise ContentValidationError(f"M01-J spell alias conflicts: {conflicts}")
    SPELL_INDEX_ALIASES.update(DIVINE_SOUL_SPELL_INDEX_ALIASES)
