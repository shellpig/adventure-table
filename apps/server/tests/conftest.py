from __future__ import annotations

from collections.abc import Callable

import pytest

from tests.m03_baseline import M03A_START_PACKS


M03_FULL_CONTENT_PACKS = M03A_START_PACKS


@pytest.fixture
def enabled_content_packs_full() -> tuple[str, ...]:
    """M03-A start baseline pack set shared by later M03 subphases.

    Sourced from ``docs/M03/baseline/m03a-start.json`` so the pack list is not
    restated in test code.
    """

    return M03_FULL_CONTENT_PACKS


@pytest.fixture
def enabled_content_packs_without(
    enabled_content_packs_full: tuple[str, ...],
) -> Callable[[str], tuple[str, ...]]:
    """Return a factory that disables one installed pack without deleting files."""

    def _without(pack: str) -> tuple[str, ...]:
        if pack not in enabled_content_packs_full:
            raise ValueError(f"unknown enabled content pack: {pack}")
        return tuple(candidate for candidate in enabled_content_packs_full if candidate != pack)

    return _without
