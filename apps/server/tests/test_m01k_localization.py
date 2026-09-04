from __future__ import annotations

from app.paths import resolve_content_root

CONTENT_PACKS_ROOT = resolve_content_root()

"""M01-K K.11 — localization policy coverage, then completeness (in that order)."""


import json
import shutil
from pathlib import Path

import m01k_support as S
from app.content.localization import SUPPORTED_CONTENT_LOCALES, LocalizableFieldPolicy
from app.content.localization_files import load_content_localization_catalog


POLICY_PATH = CONTENT_PACKS_ROOT / "localization" / "localizable-fields.json"
FEAT_LOCALE_SHARD = CONTENT_PACKS_ROOT / "phb2014" / "locales" / "zh-TW" / "m01k-feats.json"
SPELL_LOCALE_SHARD = CONTENT_PACKS_ROOT / "phb2014" / "locales" / "zh-TW" / "m01k-spells.json"


def _mirror_locale_tree(destination: Path, registry) -> Path:
    """Copy just the policy and locale overlays so a shard can be edited safely."""

    shutil.copytree(
        CONTENT_PACKS_ROOT / "localization",
        destination / "localization",
    )
    for source in registry.enabled_pack_ids:
        locales = CONTENT_PACKS_ROOT / source / "locales"
        if locales.exists():
            shutil.copytree(locales, destination / source / "locales")
        else:
            (destination / source).mkdir(parents=True, exist_ok=True)
    return destination


def _phb_issues(registry, root: Path, kinds: set[str]):
    catalog = load_content_localization_catalog(registry, root)
    return catalog.completeness_issues(
        locales=SUPPORTED_CONTENT_LOCALES,
        sources={"phb2014"},
        kinds=kinds,
    )


# --- policy coverage first ----------------------------------------------------


def test_policy_requires_phb_feat_and_spell_descriptions_in_both_locales() -> None:
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)

    for kind in ("feat", "spell"):
        rule = policy.rule_for("phb2014", kind, "data.desc.0")
        assert rule is not None, kind
        assert rule.localizable is True
        assert rule.currently_user_visible is True
        for locale in SUPPORTED_CONTENT_LOCALES:
            assert policy.is_required("phb2014", kind, "data.desc.0", locale), (kind, locale)


def test_the_wildcard_name_rule_survives_the_description_rules() -> None:
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)

    for kind in ("feat", "spell"):
        for locale in SUPPORTED_CONTENT_LOCALES:
            assert policy.is_required("phb2014", kind, "name", locale)
            assert policy.is_required("srd5.1", kind, "name", locale)


def test_policy_rules_are_unique_and_reference_supported_locales_only() -> None:
    raw = json.loads(POLICY_PATH.read_text(encoding="utf-8"))
    seen: set[tuple[str, str, str]] = set()

    assert set(raw["supported_locales"]) == set(SUPPORTED_CONTENT_LOCALES)
    for rule in raw["rules"]:
        identity = (rule["pack"], rule["kind"], rule["field_path"])
        assert identity not in seen, identity
        seen.add(identity)
        assert set(rule["required_locales"]) <= set(SUPPORTED_CONTENT_LOCALES), identity


# --- then completeness, and only then -----------------------------------------


def test_phb_feat_and_spell_localization_is_complete() -> None:
    registry = S.registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)
    issues = catalog.completeness_issues(
        locales=SUPPORTED_CONTENT_LOCALES,
        sources={"phb2014"},
        kinds={"feat", "spell"},
    )

    assert not issues, "\n".join(
        f"{issue.key} :: {issue.field_path} :: {issue.locale}" for issue in issues
    )


def test_a_missing_feat_description_translation_fails_the_gate(tmp_path: Path) -> None:
    registry = S.registry()
    root = _mirror_locale_tree(tmp_path / "data", registry)
    shard = root / "phb2014" / "locales" / "zh-TW" / "m01k-feats.json"
    payload = json.loads(shard.read_text(encoding="utf-8"))
    key = "phb2014:feat:tough"
    original = dict(payload["entries"][key])

    assert _phb_issues(registry, root, {"feat"}) == ()

    payload["entries"][key] = {"name": original["name"]}
    shard.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    issues = _phb_issues(registry, root, {"feat"})
    assert [(issue.key, issue.locale) for issue in issues] == [(key, "zh-TW")]
    assert issues[0].field_path.startswith("data.desc.")

    payload["entries"][key] = original
    shard.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert _phb_issues(registry, root, {"feat"}) == ()


def test_a_missing_spell_description_translation_fails_the_gate(tmp_path: Path) -> None:
    registry = S.registry()
    root = _mirror_locale_tree(tmp_path / "data", registry)
    shard = root / "phb2014" / "locales" / "zh-TW" / "m01k-spells.json"
    payload = json.loads(shard.read_text(encoding="utf-8"))
    key = next(iter(payload["entries"]))
    original = dict(payload["entries"][key])

    assert _phb_issues(registry, root, {"spell"}) == ()

    payload["entries"][key] = {"name": original["name"]}
    shard.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    issues = _phb_issues(registry, root, {"spell"})
    assert [(issue.key, issue.locale) for issue in issues] == [(key, "zh-TW")]

    payload["entries"][key] = original
    shard.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    assert _phb_issues(registry, root, {"spell"}) == ()


def test_every_enabled_pack_stays_localization_complete() -> None:
    registry = S.registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)

    assert catalog.completeness_issues(locales=SUPPORTED_CONTENT_LOCALES) == ()


# --- presentation / materialization -------------------------------------------


def test_all_forty_one_feats_and_forty_two_spells_have_zh_tw_names_and_descriptions() -> None:
    registry = S.registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)

    feats = registry.list_kind("feat", source="phb2014")
    spells = registry.list_kind("spell", source="phb2014")
    assert len(feats) == 41
    assert len(spells) == 42

    for entry in (*feats, *spells):
        for locale in SUPPORTED_CONTENT_LOCALES:
            name = catalog.resolve_name(entry.key, locale)
            assert name.value.strip(), (entry.key, locale)
            for index in range(len(entry.data["desc"])):
                field = catalog.resolve_field(entry.key, f"data.desc.{index}", locale)
                assert field.value.strip(), (entry.key, index, locale)


def test_locale_switching_never_changes_a_stable_key_or_mechanic() -> None:
    registry = S.registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)

    for entry in registry.list_kind("feat", source="phb2014"):
        english = catalog.resolve_name(entry.key, "en").value
        chinese = catalog.resolve_name(entry.key, "zh-TW").value
        assert english == entry.name
        assert chinese != "" and entry.key.startswith("phb2014:feat:")
        # Mechanics stay locale-neutral.
        assert isinstance(entry.data["prerequisites"], list)
        assert entry.data["automation"].isascii()


def test_the_reference_markdown_is_not_needed_at_runtime() -> None:
    """K.11 runtime-without-docs gate: no runtime path reads the authoring notes."""

    registry = S.registry()
    for entry in (
        *registry.list_kind("feat", source="phb2014"),
        *registry.list_kind("spell", source="phb2014"),
    ):
        reference = entry.provenance.get("reference_doc", "")
        # Provenance may name the authoring source, but the loaded content must be
        # self-contained: descriptions and mechanics already live in the pack.
        assert entry.data["desc"]
        assert "docs/" not in json.dumps(entry.data, ensure_ascii=False), entry.key
        assert reference == "" or reference.startswith("docs/")
