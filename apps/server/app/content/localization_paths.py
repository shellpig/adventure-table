from __future__ import annotations

from typing import Any, Mapping


def localization_path_tokens(path: str) -> tuple[str, ...]:
    """Parse a concrete localization field path into traversal tokens."""

    if not path or path.startswith(".") or path.endswith("."):
        raise ValueError(f"invalid localization field path: {path!r}")
    return tuple(path.split("."))


def read_localization_path(root: Any, path: str) -> Any:
    """Read a concrete field path from a canonical content payload.

    Runtime localization resolution and structural overlay validation both use
    this public helper so field-path semantics have one implementation.
    """

    current = root
    for token in localization_path_tokens(path):
        if isinstance(current, Mapping):
            if token not in current:
                raise KeyError(path)
            current = current[token]
            continue
        if isinstance(current, (list, tuple)) and token.isdigit():
            position = int(token)
            if position >= len(current):
                raise KeyError(path)
            current = current[position]
            continue
        raise KeyError(path)
    return current


__all__ = ["localization_path_tokens", "read_localization_path"]
