from __future__ import annotations

from pathlib import Path

import pytest

from app.content import load_default_content_registry
from app.content.localization import (
    ContentLocalizationCatalog,
    LocalizableFieldPolicy,
    LocalizableFieldRule,
    TerminologyGlossary,
    roleplay_suggestion_id,
)
from app.content.registry import CONTENT_PACKS_ROOT, DEFAULT_CONTENT_ROOT, ContentRegistry
from app.domain.character_builder.schemas import BuilderDraftPayload


POLICY_PATH = CONTENT_PACKS_ROOT / "localization" / "localizable-fields.json"
GLOSSARY_PATH = CONTENT_PACKS_ROOT / "localization" / "dnd5e-2014-glossary.json"


def _srd_catalog(
    overlays: dict[tuple[str, str], dict[str, dict[str, object]]] | None = None,
) -> ContentLocalizationCatalog:
    registry = ContentRegistry.from_directory(DEFAULT_CONTENT_ROOT)
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)
    return ContentLocalizationCatalog(registry, policy, overlays)


def test_stable_key_and_mechanics_do_not_change_with_locale() -> None:
    key = "srd5.1:spell:fireball"
    catalog = _srd_catalog(
        {
            ("srd5.1", "zh-TW"): {
                key: {"name": "火球術"},
            }
        }
    )
    before = catalog.registry.get(key).model_dump(mode="python")

    en = catalog.resolve_name(key, "en")
    zh = catalog.resolve_name(key, "zh-TW")

    assert en.key == zh.key == key
    assert en.value == "Fireball"
    assert zh.value == "火球術"
    assert en.canonical_value == zh.canonical_value == "Fireball"
    assert catalog.registry.get(key).model_dump(mode="python") == before
    assert catalog.registry.get(key).data["level"] == before["data"]["level"]


def test_resolver_supports_current_rules_presentation_kinds_and_long_text() -> None:
    registry = ContentRegistry.from_directory(DEFAULT_CONTENT_ROOT)
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)
    kinds = (
        "race",
        "background",
        "proficiency",
        "skill",
        "equipment",
        "item",
        "spell",
        "feature",
    )
    entries = [registry.list_kind(kind)[0] for kind in kinds]
    translations = {
        entry.key: {"name": f"zh::{entry.index}"}
        for entry in entries
    }
    spell = next(
        entry
        for entry in registry.list_kind("spell")
        if isinstance(entry.data.get("desc"), list) and entry.data["desc"]
    )
    translations.setdefault(spell.key, {})["data.desc.0"] = "zh::long-description"
    catalog = ContentLocalizationCatalog(
        registry,
        policy,
        {("srd5.1", "zh-TW"): translations},
    )

    for entry in entries:
        resolved = catalog.resolve_name(entry.key, "zh-TW")
        assert resolved.value == f"zh::{entry.index}"
        assert not resolved.missing_required

    long_text = catalog.resolve_field(spell.key, "data.desc.0", "zh-TW")
    assert long_text.value == "zh::long-description"
    assert long_text.source == "overlay"


def test_field_policy_distinguishes_visible_item_name_from_hidden_long_description() -> None:
    catalog = _srd_catalog()
    item = catalog.registry.list_kind("item")[0]

    assert catalog.policy.is_required("srd5.1", "item", "name", "zh-TW")
    assert not catalog.policy.is_required("srd5.1", "item", "data.desc.0", "zh-TW")

    missing_name = catalog.resolve_field(item.key, "name", "zh-TW")
    assert missing_name.fallback_used
    assert missing_name.missing_required

    if item.data.get("desc"):
        hidden_desc = catalog.resolve_field(item.key, "data.desc.0", "zh-TW")
        assert hidden_desc.fallback_used
        assert not hidden_desc.missing_required

    required_desc_policy = LocalizableFieldPolicy(
        (
            LocalizableFieldRule(
                pack="srd5.1",
                kind="item",
                field_path="data.desc.*",
                localizable=True,
                currently_user_visible=True,
                required_locales=("zh-TW", "en"),
                surfaces=("fixture",),
                reason="Fixture promotes item descriptions to a visible surface.",
            ),
        )
    )
    required_desc_catalog = ContentLocalizationCatalog(
        catalog.registry,
        required_desc_policy,
    )
    if item.data.get("desc"):
        promoted = required_desc_catalog.resolve_field(item.key, "data.desc.0", "zh-TW")
        assert promoted.missing_required


def test_missing_required_translation_is_diagnostic_and_completeness_uses_same_policy() -> None:
    catalog = _srd_catalog()
    issues = catalog.completeness_issues(
        locales=("zh-TW",),
        sources={"srd5.1"},
        kinds={"item"},
    )

    assert issues
    assert all(issue.locale == "zh-TW" for issue in issues)
    assert any(issue.field_path == "name" for issue in issues)
    assert not any(issue.field_path.startswith("data.desc.") for issue in issues)


def test_roleplay_system_suggestion_identity_is_locale_neutral_and_draft_can_persist_it() -> None:
    registry = load_default_content_registry()
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)
    background = next(
        entry
        for entry in registry.list_kind("background")
        if isinstance(entry.data.get("roleplay_suggestions"), dict)
        and any(
            isinstance(entry.data["roleplay_suggestions"].get(field), list)
            and entry.data["roleplay_suggestions"][field]
            for field in ("personality_traits", "ideals", "bonds", "flaws")
        )
    )
    field = next(
        field
        for field in ("personality_traits", "ideals", "bonds", "flaws")
        if background.data["roleplay_suggestions"].get(field)
    )
    path = f"data.roleplay_suggestions.{field}.0"
    overlay = {
        (background.source, "zh-TW"): {
            background.key: {path: "系統建議（測試翻譯）"},
        }
    }
    catalog = ContentLocalizationCatalog(registry, policy, overlay)

    en = next(
        item
        for item in catalog.roleplay_suggestions(background.key, "en")
        if item.field == field and item.position == 0
    )
    zh = next(
        item
        for item in catalog.roleplay_suggestions(background.key, "zh-TW")
        if item.field == field and item.position == 0
    )

    assert en.suggestion_id == zh.suggestion_id == roleplay_suggestion_id(
        background.key, field, 0
    )
    assert en.text != zh.text
    assert zh.text == "系統建議（測試翻譯）"

    # The Draft payload is persisted JSON and deliberately supports a parallel
    # identity map without changing the free-text roleplay fields. Older drafts
    # with only arrays of strings remain valid.
    manual_text = "This is player-authored text and must remain verbatim."
    payload = BuilderDraftPayload.model_validate(
        {
            "roleplay_profile": {
                field: [manual_text],
                "system_suggestion_refs": {
                    field: [
                        {
                            "suggestion_id": en.suggestion_id,
                            "position": 0,
                        }
                    ]
                },
            }
        }
    )
    persisted = payload.model_dump(mode="python")["roleplay_profile"]
    assert persisted[field] == [manual_text]
    assert persisted["system_suggestion_refs"][field][0]["suggestion_id"] == en.suggestion_id


def test_glossary_is_fully_reviewed_and_runtime_independent_from_reference_markdown() -> None:
    glossary = TerminologyGlossary.from_path(GLOSSARY_PATH)

    assert glossary.terms
    assert all(term.reviewed for term in glossary.terms)
    assert {"Race", "Background", "Feature", "Infusion"}.issubset(
        {term.term for term in glossary.terms}
    )
    assert all(
        term.reference_zh_tw == term.zh_tw or term.decision_note
        for term in glossary.terms
        if term.reference_zh_tw is not None
    )
    assert all(
        not (term.reference_source or "").endswith(".md")
        or term.reference_source.startswith("docs/暫用規則資訊/")
        for term in glossary.terms
    )
