"""M01-M M.1 / M.3 / M.12 — pack identity, Tiefling accounting, localization scope."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.m01m_inventory import INVENTORY_PATH, validate_m01m_inventory
from app.content.registry import CONTENT_PACKS_ROOT, ContentValidationError


REPO_ROOT = Path(__file__).resolve().parents[3]

SRD_TIEFLING = "srd5.1:race:tiefling"
SCAG_TIEFLING_VARIANT = "scag:race-variant:tiefling-variants"

PLANAR_SCOPE = {
    "mtf:subrace:duergar": "srd5.1:race:dwarf",
    "mtf:subrace:eladrin": "srd5.1:race:elf",
    "mtf:subrace:sea-elf": "srd5.1:race:elf",
    "mtf:subrace:shadar-kai": "srd5.1:race:elf",
    "mtf:race:gith": None,
    "mtf:subrace:githyanki": "mtf:race:gith",
    "mtf:subrace:githzerai": "mtf:race:gith",
}

BLOODLINE_VARIANTS = {
    "mtf:race-variant:baalzebul-tiefling",
    "mtf:race-variant:dispater-tiefling",
    "mtf:race-variant:fierna-tiefling",
    "mtf:race-variant:glasya-tiefling",
    "mtf:race-variant:levistus-tiefling",
    "mtf:race-variant:mammon-tiefling",
    "mtf:race-variant:mephistopheles-tiefling",
    "mtf:race-variant:zariel-tiefling",
}


def _inventory() -> dict:
    return json.loads(INVENTORY_PATH.read_text(encoding="utf-8"))


def test_mtf_is_an_enabled_pack_whose_manifest_matches_its_shipped_entries() -> None:
    registry = load_default_content_registry()

    assert "mtf" in registry.enabled_pack_ids

    manifest = json.loads((CONTENT_PACKS_ROOT / "mtf" / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["id"] == "mtf"
    assert manifest["ruleset"] == "dnd5e-2014"

    total = 0
    for category in manifest["categories"]:
        shipped = registry.list_kind(category["kind"], source="mtf")
        assert len(shipped) == category["count"], category["kind"]
        total += category["count"]
    assert total == manifest["total_entries"]


def test_planar_scope_is_exactly_seven_identities_with_declared_parents() -> None:
    registry = load_default_content_registry()

    races = {entry.key for entry in registry.list_kind("race", source="mtf")}
    subraces = {entry.key for entry in registry.list_kind("subrace", source="mtf")}
    assert races | subraces == set(PLANAR_SCOPE)

    for key, parent in PLANAR_SCOPE.items():
        entry = registry.get(key)
        assert entry.source == "mtf", key
        if parent is None:
            assert "race" not in entry.data, key
            continue
        assert entry.data["race"]["key"] == parent, key
        # A subrace's parent must be an installed race, not a dangling ref.
        assert registry.get(parent).key == parent


def test_tiefling_bloodlines_account_for_nine_with_asmodeus_mapped_to_srd() -> None:
    registry = load_default_content_registry()
    bloodlines = _inventory()["tiefling_bloodlines"]

    assert len(bloodlines) == 9
    canonical = [row for row in bloodlines if row["disposition"] == "canonical_mapping"]
    variants = [row for row in bloodlines if row["disposition"] == "implemented_variant"]

    assert [row["name"] for row in canonical] == ["Asmodeus"]
    assert canonical[0]["key"] == SRD_TIEFLING
    assert {row["key"] for row in variants} == BLOODLINE_VARIANTS

    # The canonical mapping is an accounting statement, not a second identity.
    assert {entry.key for entry in registry.list_kind("race-variant", source="mtf")} == BLOODLINE_VARIANTS
    assert not [key for key in BLOODLINE_VARIANTS if "asmodeus" in key]
    assert registry.get(SRD_TIEFLING).source == "srd5.1"


def test_every_tiefling_variant_hangs_off_the_existing_srd_tiefling() -> None:
    registry = load_default_content_registry()

    for key in BLOODLINE_VARIANTS | {SCAG_TIEFLING_VARIANT}:
        assert registry.get(key).data["base_race_ref"]["key"] == SRD_TIEFLING, key


class _RegistryWithout:
    """A registry view with one identity removed, to prove the gate is load-bearing."""

    def __init__(self, registry, missing: str) -> None:
        self._registry = registry
        self._missing = missing

    def get_optional(self, key: str):
        return None if key == self._missing else self._registry.get_optional(key)

    def list_kind(self, kind: str, *, source: str | None = None):
        return tuple(
            entry
            for entry in self._registry.list_kind(kind, source=source)
            if entry.key != self._missing
        )


@pytest.mark.parametrize(
    "missing",
    ["mtf:race:gith", "mtf:subrace:sea-elf", "mtf:race-variant:zariel-tiefling"],
)
def test_inventory_gate_rejects_a_registry_missing_a_declared_identity(missing: str) -> None:
    registry = load_default_content_registry()

    validate_m01m_inventory(registry)
    with pytest.raises(ContentValidationError):
        validate_m01m_inventory(_RegistryWithout(registry, missing))


def test_m01m_localization_scope_is_complete_in_both_locales() -> None:
    registry = load_default_content_registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)

    issues = catalog.completeness_issues(
        locales=("zh-TW", "en"),
        sources={"mtf"},
        kinds={"race", "subrace", "race-variant", "feature", "language"},
    )
    assert issues == (), ", ".join(
        f"{issue.key}::{issue.field_path}::{issue.locale}" for issue in issues[:20]
    )

    # The optional appearance helper is presentation and must be bilingual;
    # the mechanics that decide legality stay locale-neutral.
    assert catalog.policy.is_required(
        "scag", "race-variant", "data.appearance_suggestions.0", "zh-TW"
    )
    assert catalog.policy.is_required("mtf", "feature", "data.desc.0", "zh-TW")
    assert not catalog.policy.is_required(
        "mtf", "subrace", "data.ability_bonuses.0.bonus", "zh-TW"
    )
    assert not catalog.policy.is_required(
        "mtf", "subrace", "data.movement_grants.0.speed", "zh-TW"
    )


def test_m01m_runtime_never_depends_on_authoring_markdown() -> None:
    authoring_markers = ("暫用規則資訊", "種族_MTF", "種族_SCAG")
    roots = (
        REPO_ROOT / "apps" / "server" / "app",
        REPO_ROOT / "apps" / "web" / "src",
    )
    offenders = [
        str(path.relative_to(REPO_ROOT))
        for root in roots
        for path in (*root.rglob("*.py"), *root.rglob("*.ts"), *root.rglob("*.tsx"))
        if any(marker in path.read_text(encoding="utf-8") for marker in authoring_markers)
    ]
    assert offenders == [], f"runtime code references authoring markdown: {offenders}"

    dockerfile = (REPO_ROOT / "apps" / "server" / "Dockerfile").read_text(encoding="utf-8")
    copied = [line for line in dockerfile.splitlines() if line.startswith("COPY ")]
    assert copied
    assert not [line for line in copied if "docs" in line]
