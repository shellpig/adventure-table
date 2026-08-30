from app.content import registry as _registry
from app.content.background_roleplay import apply_background_roleplay_inheritance
from app.content.phb_roleplay import apply_phb_background_roleplay
from app.content.registry import (
    ContentNotFoundError,
    ContentRegistry,
    ContentValidationError,
)


# Production/dev packs are explicit. M01-C enables SCAG / GoS only after their
# normalized manifests and data exist; fixture directories remain opt-in in tests.
_registry.DEFAULT_CONTENT_PACKS = ("srd5.1", "phb2014", "scag", "gos")


def load_default_content_registry() -> ContentRegistry:
    registry = _registry.load_default_content_registry()
    registry = apply_phb_background_roleplay(
        registry,
        content_root=_registry.CONTENT_PACKS_ROOT,
    )
    return apply_background_roleplay_inheritance(registry)


__all__ = [
    "ContentNotFoundError",
    "ContentRegistry",
    "ContentValidationError",
    "load_default_content_registry",
]
