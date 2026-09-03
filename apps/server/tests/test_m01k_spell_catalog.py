"""M01-K K.7 / K.8 / K.9 — spell reconciliation, canonical metadata, provenance."""

from __future__ import annotations

import json

import m01k_support as S
from app.content.registry import CONTENT_PACKS_ROOT


PHB_ROOT = CONTENT_PACKS_ROOT / "phb2014"
M01I_SHARD = "spells-m01i.json"
M01J_SHARD = "spells-m01j.json"
K_SHARDS = ("spells-m01k-01.json", "spells-m01k-02.json")

REQUIRED_SPELL_FIELDS = (
    "name",
    "level",
    "school",
    "casting_time",
    "range",
    "components",
    "duration",
    "ritual",
    "concentration",
    "classes",
    "desc",
)


def _shard_keys(name: str) -> list[str]:
    rows = json.loads((PHB_ROOT / name).read_text(encoding="utf-8"))
    return [row["key"] for row in rows]


def _manifest_spell_categories() -> list[dict]:
    manifest = json.loads((PHB_ROOT / "manifest.json").read_text(encoding="utf-8"))
    return [category for category in manifest["categories"] if category["kind"] == "spell"]


def _phb_spells(content):
    return tuple(content.list_kind("spell", source="phb2014"))


# --- K.7 inventory reconciliation ---------------------------------------------


def test_the_phb_spell_catalog_accounts_for_exactly_forty_two_identities() -> None:
    content = S.registry()
    spells = _phb_spells(content)

    assert len(spells) == 42
    assert len({entry.key for entry in spells}) == 42


def test_existing_m01i_and_m01j_spell_identities_are_reused_not_duplicated() -> None:
    existing = _shard_keys(M01I_SHARD) + _shard_keys(M01J_SHARD)
    added = [key for shard in K_SHARDS for key in _shard_keys(shard)]

    assert existing, "M01-I / M01-J must still own their original shards"
    assert set(existing).isdisjoint(added)
    assert len(existing) + len(added) == 42
    assert len(set(existing + added)) == 42


def test_previously_provisional_entries_carry_complete_metadata_now() -> None:
    """Identity already existing is not the same as being complete."""

    content = S.registry()
    for key in _shard_keys(M01I_SHARD) + _shard_keys(M01J_SHARD):
        data = content.get(key).data
        for field in REQUIRED_SPELL_FIELDS:
            assert field in data, f"{key} is missing {field}"
        assert data["desc"], f"{key} still has an empty description"
        assert data["classes"], f"{key} still has no class access"


def test_manifest_counts_match_the_installed_spell_entries() -> None:
    categories = _manifest_spell_categories()
    total = 0
    for category in categories:
        rows = json.loads((PHB_ROOT / category["file"]).read_text(encoding="utf-8"))
        assert len(rows) == category["count"], category["file"]
        total += category["count"]

    assert total == 42
    assert {category["file"] for category in categories} == {M01I_SHARD, M01J_SHARD, *K_SHARDS}


def test_every_phb_spell_key_resolves_through_the_registry() -> None:
    content = S.registry()
    for shard in (M01I_SHARD, M01J_SHARD, *K_SHARDS):
        for key in _shard_keys(shard):
            assert content.get_optional(key) is not None, key


# --- K.8 canonical metadata ---------------------------------------------------


def test_all_forty_two_spells_carry_the_required_canonical_metadata() -> None:
    content = S.registry()
    for entry in _phb_spells(content):
        data = entry.data
        assert entry.name
        assert entry.source == "phb2014"
        assert isinstance(data["level"], int) and 0 <= data["level"] <= 9
        assert isinstance(data["school"], dict) and data["school"].get("key")
        assert data["casting_time"].strip()
        assert data["range"].strip()
        assert data["duration"].strip()
        assert set(data["components"]) <= {"V", "S", "M"} and data["components"]
        assert isinstance(data["ritual"], bool)
        assert isinstance(data["concentration"], bool)
        assert data["classes"]
        assert data["desc"] and all(row.strip() for row in data["desc"])
        assert entry.provenance["rules_source"]


def test_material_components_name_their_material() -> None:
    content = S.registry()
    checked = 0
    for entry in _phb_spells(content):
        if "M" in entry.data["components"]:
            assert entry.data.get("material", "").strip(), entry.key
            checked += 1
    assert checked > 0


def test_focused_metadata_shapes_are_all_represented() -> None:
    content = S.registry()
    by_key = {entry.key: entry.data for entry in _phb_spells(content)}

    assert by_key["phb2014:spell:blade-ward"]["level"] == 0
    assert by_key["phb2014:spell:arcane-gate"]["concentration"] is True
    assert by_key["phb2014:spell:beast-sense"]["ritual"] is True
    assert "bonus action" in by_key["phb2014:spell:banishing-smite"]["casting_time"].lower()
    assert "M" in by_key["phb2014:spell:armor-of-agathys"]["components"]
    assert by_key["phb2014:spell:power-word-heal"]["level"] == 9
    assert len(by_key["phb2014:spell:arcane-gate"]["classes"]) > 1


def test_school_and_class_references_resolve_to_real_content() -> None:
    content = S.registry()
    for entry in _phb_spells(content):
        assert content.get_optional(entry.data["school"]["key"]) is not None, entry.key
        for reference in entry.data["classes"]:
            assert content.get_optional(reference["key"]) is not None, entry.key


# --- K.9 cross-source access provenance ---------------------------------------


def test_phb_provenance_lists_only_phb_class_access() -> None:
    content = S.registry()

    thorn_whip = content.get("phb2014:spell:thorn-whip")
    elemental_weapon = content.get("phb2014:spell:elemental-weapon")

    assert [reference["key"] for reference in thorn_whip.data["classes"]] == [
        "srd5.1:class:druid"
    ]
    assert [reference["key"] for reference in elemental_weapon.data["classes"]] == [
        "srd5.1:class:paladin"
    ]
    for entry in (thorn_whip, elemental_weapon):
        assert "tce:class:artificer" not in {
            reference["key"] for reference in entry.data["classes"]
        }
        assert entry.provenance["rules_source"].startswith("Player's Handbook")


def test_no_later_source_clones_a_phb_spell_identity() -> None:
    content = S.registry()
    phb_indices = {entry.data["index"] for entry in _phb_spells(content)}
    clones = [
        entry.key
        for entry in content.list_kind("spell")
        if entry.source != "phb2014" and entry.data.get("index") in phb_indices
    ]

    assert clones == []


def test_artificer_does_not_inherit_access_from_the_phb_entry_alone() -> None:
    """A PHB identity is not a licence for later-source class access."""

    content = S.registry()
    from app.domain.character_builder.schemas import BuilderLevelChoice

    levels = tuple(
        BuilderLevelChoice(
            character_level=index,
            class_ref="tce:class:artificer",
            hp_method="first_level" if index == 1 else "fixed_average",
            hp_base_gain=8 if index == 1 else 5,
            subclass_ref="tce:subclass:artillerist" if index == 3 else None,
        )
        for index in range(1, 6)
    )
    base = S.auto_fill(S.payload(levels), content, skip_sources=set())
    result, _ = S.compile_payload(base, content)

    available = {
        option.spell_key
        for profile in result.resolved_summary.spellcasting_profiles
        for option in profile.available_spells
    }
    assert "phb2014:spell:thorn-whip" not in available
    assert "phb2014:spell:elemental-weapon" not in available


def test_a_later_source_overlay_can_expand_access_to_a_phb_spell() -> None:
    """Searing Smite is Paladin-only in the PHB; TCE lends it to the Ranger."""

    content = S.registry()
    searing_smite = "phb2014:spell:searing-smite"
    assert [reference["key"] for reference in content.get(searing_smite).data["classes"]] == [
        "srd5.1:class:paladin"
    ]

    levels = S.class_levels(
        "ranger", 5, first_hp=10, later_hp=6, subclass_ref="srd5.1:subclass:hunter", subclass_level=3
    )
    base = S.fill_spell_choices(
        S.auto_fill(S.payload(levels), content, skip_sources=set()), content
    )
    result, _ = S.compile_payload(base, content)

    assert S.issue_codes(result) == set()
    profile = S.spell_profile(result, "class:ranger")
    available = {option.spell_key for option in profile.available_spells}
    assert searing_smite in available
    # Expanded access is eligibility only: nothing is auto-known, and the spell
    # keeps its PHB identity rather than gaining a TCE one.
    assert searing_smite not in profile.selected_known_spell_keys
    assert content.get(searing_smite).source == "phb2014"
