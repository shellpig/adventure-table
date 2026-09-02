from app.content import registry as _registry
from app.content.background_roleplay import apply_background_roleplay_inheritance
from app.content.builder_content_validation import validate_builder_content
from app.content.m01i_inventory import validate_m01i_inventory
from app.content.m01j_closeout_validation import validate_m01j_closeout_metadata
from app.content.m01j_inventory import (
    apply_m01j_subclass_relations,
    validate_m01j_inventory,
)
from app.content.m01j_reference_closeout import apply_m01j_reference_closeout
from app.content.m01j_reference_completion import apply_m01j_reference_completion
from app.content.m01j_reference_content import apply_m01j_reference_content
from app.content.m01j_spell_closeout_validation import validate_m01j_spell_closeout
from app.content.phb_roleplay import apply_phb_background_roleplay
from app.content.registry import (
    ContentNotFoundError,
    ContentRegistry,
    ContentValidationError,
)


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
    # M01-J's verified non-SRD mechanics are repository reference documents.
    # Materialize their temporary runtime overlay, normalize the handful of
    # rules whose permanent semantics span multiple Markdown sections/tables,
    # then finish spell-choice semantics that require cross-feature context.
    registry = apply_m01j_reference_content(registry)
    registry = apply_m01j_reference_completion(registry)
    registry = apply_m01j_reference_closeout(registry)
    registry = validate_m01j_inventory(registry)
    registry = validate_m01j_closeout_metadata(registry)
    registry = validate_m01j_spell_closeout(registry)
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
