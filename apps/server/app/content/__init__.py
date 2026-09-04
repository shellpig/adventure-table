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
from app.content.m01m_inventory import validate_m01m_inventory
from app.content.m01m_models import install_m01m_content_models
from app.content.m01m_overrides import apply_m01m_entry_overrides
from app.content.phb_roleplay import apply_phb_background_roleplay
from app.content.registry import (
    ContentNotFoundError,
    ContentRegistry,
    ContentValidationError,
)
from app.paths import resolve_content_root


install_m01l_content_models()
install_m01m_content_models()


_M01I_REQUIRED_PACKS = frozenset({"srd5.1", "tce"})
_M01J_OVERRIDE_REQUIRED_PACKS = frozenset({"srd5.1", "phb2014", "tce"})
_M01J_CLOSEOUT_REQUIRED_PACKS = frozenset(
    {"srd5.1", "phb2014", "scag", "xge", "tce"}
)
_M01L_REQUIRED_PACKS = frozenset({"srd5.1", "scag", "vgm", "xge"})
_M01M_REQUIRED_PACKS = frozenset({"srd5.1", "scag", "vgm", "mtf"})


def _has_enabled_packs(registry: ContentRegistry, required: frozenset[str]) -> bool:
    return required.issubset(registry.enabled_pack_ids)


def load_default_content_registry() -> ContentRegistry:
    registry = _registry.load_default_content_registry()
    registry = validate_builder_content(registry)

    # Phase closeout validators describe a complete source set. In M03 a
    # deliberately disabled pack is an unavailable dependency, not corrupted
    # checked-in content, so only run a phase gate when all of its source packs
    # are active. The default nine-pack web path still executes every gate.
    if _has_enabled_packs(registry, _M01I_REQUIRED_PACKS):
        registry = validate_m01i_inventory(registry)

    # M01-J's SRD patches add references into PHB/TCE option pools, so they are
    # only safe when those packs are enabled. The stricter closeout/inventory
    # gates additionally require the full M01-J source set.
    if _has_enabled_packs(registry, _M01J_OVERRIDE_REQUIRED_PACKS):
        registry = apply_m01j_entry_overrides(registry)
    if _has_enabled_packs(registry, _M01J_CLOSEOUT_REQUIRED_PACKS):
        registry = validate_m01j_inventory(registry)
        registry = validate_m01j_closeout_metadata(registry)
        registry = validate_m01j_spell_closeout(registry)
        registry = apply_m01j_subclass_relations(registry)

    if _has_enabled_packs(registry, _M01L_REQUIRED_PACKS):
        registry = validate_m01l_inventory(registry)

    # The canonical SRD Tiefling baseline only references SRD spells, so its
    # typed racial-spell metadata remains valid even when MTF is disabled.
    if "srd5.1" in registry.enabled_pack_ids:
        registry = apply_m01m_entry_overrides(registry)
    if _has_enabled_packs(registry, _M01M_REQUIRED_PACKS):
        registry = validate_m01m_inventory(registry)

    if "phb2014" in registry.enabled_pack_ids:
        registry = apply_phb_background_roleplay(
            registry,
            content_root=resolve_content_root(),
        )
    return apply_background_roleplay_inheritance(registry)


__all__ = [
    "ContentNotFoundError",
    "ContentRegistry",
    "ContentValidationError",
    "load_default_content_registry",
]
