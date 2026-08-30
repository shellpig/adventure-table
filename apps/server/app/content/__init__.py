from app.content import registry as _registry
from app.content.registry import (
    ContentNotFoundError,
    ContentRegistry,
    ContentValidationError,
)


# Production/dev packs are explicit. M01-B enables PHB only after its manifest
# and normalized data exist; fixture directories remain opt-in in tests.
_registry.DEFAULT_CONTENT_PACKS = ("srd5.1", "phb2014")
load_default_content_registry = _registry.load_default_content_registry

__all__ = [
    "ContentNotFoundError",
    "ContentRegistry",
    "ContentValidationError",
    "load_default_content_registry",
]
