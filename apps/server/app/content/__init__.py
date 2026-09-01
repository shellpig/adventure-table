from app.content import registry as _registry
from app.content.background_roleplay import apply_background_roleplay_inheritance
from app.content.builder_content_validation import validate_builder_content
from app.content.m01i_inventory import validate_m01i_inventory
from app.content.m01j_inventory import (
    apply_m01j_subclass_relations,
    validate_m01j_inventory,
)
from app.content.phb_roleplay import apply_phb_background_roleplay
from app.content.registry import (
    ContentNotFoundError,
    ContentRegistry,
    ContentValidationError,
)


# Production/dev packs are explicit. M01-J introduces the XGE pack boundary
# before source-backed subclass runtime data is available; the M01-J inventory
# validator keeps those explicit data blockers separate from implemented content.
_registry.DEFAULT_CONTENT_PACKS = (
    "srd5.1",
    "phb2014",
    "scag",
    "gos",
    "vgm",
    "vrgr",
    "tce",
    "xge",
)


def load_default_content_registry() -> ContentRegistry:
    registry = _registry.load_default_content_registry()
    registry = validate_builder_content(registry)
    registry = validate_m01i_inventory(registry)
    registry = validate_m01j_inventory(registry)
    registry = apply_m01j_subclass_relations(registry)
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
