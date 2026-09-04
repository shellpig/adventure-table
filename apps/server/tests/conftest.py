from __future__ import annotations

from collections.abc import Callable

import pytest


M03_FULL_CONTENT_PACKS = (
    "srd5.1",
    "phb2014",
    "scag",
    "gos",
    "vgm",
    "vrgr",
    "tce",
    "xge",
    "mtf",
)


@pytest.fixture
def enabled_content_packs_full() -> tuple[str, ...]:
    """M03-A start baseline pack set shared by later M03 subphases."""

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
