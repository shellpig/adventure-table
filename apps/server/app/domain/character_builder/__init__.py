from __future__ import annotations

from typing import TYPE_CHECKING, Any

from app.domain.character_builder.schemas import (
    BuilderChoice,
    BuilderDraft,
    BuilderDraftCreateInput,
    BuilderDraftPatchInput,
    BuilderIssue,
    BuilderIssueSeverity,
    BuilderMode,
    BuilderValidationResult,
    BuilderView,
)

if TYPE_CHECKING:
    from app.domain.character_builder.service import CharacterBuilderService


def __getattr__(name: str) -> Any:
    """Keep the package-level service export without eager persistence imports.

    Alembic imports persistence table modules while constructing metadata. P1-G
    reconciliation lives under this package and is imported by the character
    repository, so eagerly importing the service here would form:
    persistence.characters -> character_builder -> service -> persistence.characters.
    """

    if name == "CharacterBuilderService":
        from app.domain.character_builder.service import CharacterBuilderService

        return CharacterBuilderService
    raise AttributeError(name)


__all__ = [
    "BuilderChoice",
    "BuilderDraft",
    "BuilderDraftCreateInput",
    "BuilderDraftPatchInput",
    "BuilderIssue",
    "BuilderIssueSeverity",
    "BuilderMode",
    "BuilderValidationResult",
    "BuilderView",
    "CharacterBuilderService",
]


# M01-I extends the established compiler without replacing its core pipeline.
# Installing here makes both direct compiler imports and service imports use the
# same extension while preserving the package's lazy persistence boundary.
from app.domain.character_builder.m01i_compiler import install_m01_i_compiler_extension

install_m01_i_compiler_extension()
