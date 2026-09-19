from __future__ import annotations

from collections.abc import Callable
import functools
from pathlib import Path

import pytest

import app.content as _content
import app.content.registry as _content_registry
from app.content.registry import ContentRegistry
from tests.m03_baseline import M03A_START_PACKS


M03_FULL_CONTENT_PACKS = M03A_START_PACKS

# Tests call ``load_default_content_registry()`` ~900 times per full run and
# each load costs ~0.4s, about half the suite's wall-clock. The default
# registry is read-only once built, so memoise it per (content root, enabled
# packs). Tests that point the resolver or the pack list elsewhere get their
# own key; ``ContentRegistry.from_directory`` / ``from_root`` stay uncached.
# Installed at conftest import so ``from app.content import
# load_default_content_registry`` in test modules binds the cached callable.
_DEFAULT_REGISTRY_CACHE: dict[tuple[Path, tuple[str, ...]], ContentRegistry] = {}
_load_default_content_registry_uncached = _content.load_default_content_registry


@functools.wraps(_load_default_content_registry_uncached)
def _load_default_content_registry_cached() -> ContentRegistry:
    key = (
        _content_registry.resolve_content_root().resolve(),
        tuple(_content_registry.settings.enabled_content_packs),
    )
    registry = _DEFAULT_REGISTRY_CACHE.get(key)
    if registry is None:
        registry = _DEFAULT_REGISTRY_CACHE[key] = _load_default_content_registry_uncached()
    return registry


_content.load_default_content_registry = _load_default_content_registry_cached


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
