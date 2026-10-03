from __future__ import annotations


class MonsterLibraryError(Exception):
    """Base error for room monster library operations."""


class MonsterTemplateNotFoundError(MonsterLibraryError):
    """Raised when a monster template is not found."""


class MonsterLibraryForbiddenError(MonsterLibraryError):
    """Raised when the actor lacks Owner or DM authority to access the library."""


class MonsterTemplateReadOnlyError(MonsterLibraryError):
    """Raised when attempting to modify or delete a built-in content template."""


class MonsterTemplateRevisionConflictError(MonsterLibraryError):
    """Raised when an expected_revision check fails for a template mutation."""


class MonsterTemplateReferencedError(MonsterLibraryError):
    """Raised when attempting to delete a template that has active references."""


class MonsterTemplateArchivedError(MonsterLibraryError):
    """Raised when attempting to use or reference an archived template."""


class InvalidMonsterTemplateRefError(MonsterLibraryError, ValueError):
    """Raised when a monster template reference format is invalid."""


class InvalidMonsterRulesError(MonsterLibraryError, ValueError):
    """Raised when monster rules validation fails."""
