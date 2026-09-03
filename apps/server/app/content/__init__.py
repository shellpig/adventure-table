from app.content import registry as _registry
from app.content.background_roleplay import apply_background_roleplay_inheritance
from app.content.builder_content_validation import validate_builder_content
from app.content.m01i_inventory import validate_m01i_inventory
from app.content.m01j_closeout_validation import validate_m01j_closeout_metadata
from app.content.m01j_overrides import apply_m01j_entry_overrides
from app.content.m01j_inventory import (
    apply_m01j_subclass_relations,
    validate_m01j_inventory,
)
from app.content.m01j_spell_closeout_validation import validate_m01j_spell_closeout
from app.content.m01l_inventory import validate_m01l_inventory
from app.content.m01l_models import install_m01l_content_models
from app.content.m01m_models import install_m01m_content_models
from app.content.phb_roleplay import apply_phb_background_roleplay
from app.content.registry import (
    ContentNotFoundError,
    ContentRegistry,
    ContentValidationError,
)


install_m01l_content_models()
install_m01m_content_models()

_registry.DEFAULT_CONTENT_PACKS = (
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


def load_default_content_registry() -> ContentRegistry:
    registry = _registry.load_default_content_registry()
    registry = validate_builder_content(registry)
    registry = validate_m01i_inventory(registry)
    # M01-J subclass content is ordinary pack data. Only the additive patches
    # onto vendored SRD entries are applied here; the gates below then check the
    # installed rows against the checked-in inventory.
    registry = apply_m01j_entry_overrides(registry)
    registry = validate_m01j_inventory(registry)
    registry = validate_m01j_closeout_metadata(registry)
    registry = validate_m01j_spell_closeout(registry)
    registry = apply_m01j_subclass_relations(registry)
    registry = validate_m01l_inventory(registry)
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
