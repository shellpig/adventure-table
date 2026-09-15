"""P4-D compatibility import for the canonical Character Current State.

P4-D originally prototyped a separate ``CharacterRuntimeState`` with its own
schema version. That violated the locked Character JSON v1 contract. Runtime
truth now lives only in :mod:`app.domain.character.schemas` and this module is
kept as a narrow import shim so no caller can accidentally persist a second
state shape.
"""

from app.domain.character.schemas import (
    CharacterConcentrationState,
    CharacterDeathSaveState,
    CharacterState,
    PersistentTemporaryEffect,
    TemporaryEffectModifier,
)


CharacterRuntimeState = CharacterState


__all__ = [
    "CharacterConcentrationState",
    "CharacterDeathSaveState",
    "CharacterRuntimeState",
    "CharacterState",
    "PersistentTemporaryEffect",
    "TemporaryEffectModifier",
]
