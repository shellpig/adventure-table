from __future__ import annotations

from uuid import UUID


class AdventureImportError(Exception):
    """Base exception for adventure import errors."""


class AdventureImportNotFoundError(AdventureImportError, LookupError):
    """Raised when an adventure import is not found."""

    def __init__(self, import_id: UUID | None = None, message: str | None = None) -> None:
        self.import_id = import_id
        detail = message or (f"Adventure import {import_id} not found" if import_id else "Adventure import not found")
        super().__init__(detail)


class AdventureImportRevisionConflictError(AdventureImportError, RuntimeError):
    """Raised when expected revision does not match current revision."""

    def __init__(
        self,
        import_id: UUID,
        expected_revision: int,
        current_revision: int,
        message: str | None = None,
    ) -> None:
        self.import_id = import_id
        self.expected_revision = expected_revision
        self.current_revision = current_revision
        detail = message or f"expected revision {expected_revision} but found {current_revision}"
        super().__init__(
            f"Adventure import {import_id} revision conflict: {detail}"
        )


class AdventureImportValidationError(AdventureImportError, ValueError):
    """Raised when import or draft validation invariants are violated."""


class AdventureImportForbiddenError(AdventureImportError, PermissionError):
    """Raised when actor lacks required room/import authority."""


class ExtractorUnavailableError(AdventureImportError):
    """Raised when an optional extraction library is not available."""
