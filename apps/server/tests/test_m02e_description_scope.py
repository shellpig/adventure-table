from __future__ import annotations

from app.content.localization import LocalizableFieldPolicy
from app.content.registry import CONTENT_PACKS_ROOT, DEFAULT_CONTENT_ROOT, ContentRegistry


POLICY_PATH = CONTENT_PACKS_ROOT / "localization" / "localizable-fields.json"

# M02-E is deliberately field-policy driven. These are the canonical SRD
# long-form fields that exist today and are explicitly deferred because no
# current product surface renders them.
DEFERRED_SRD_LONG_FORM_RULES = {
    ("background", "data.feature.desc"),
    ("item", "data.desc.*"),
    ("spell", "data.desc.*"),
    ("condition", "data.desc.*"),
}


def _srd_rule_applies(pack: str, rule_pack: str) -> bool:
    return rule_pack in {"*", pack}


def _is_long_form(field_path: str) -> bool:
    parts = field_path.split(".")
    return any(part in {"desc", "description", "text"} for part in parts)


def test_m02e_has_no_policy_required_srd_long_form_fields_on_current_surfaces() -> None:
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)

    required = {
        (rule.kind, rule.field_path)
        for rule in policy.rules
        if _srd_rule_applies("srd5.1", rule.pack)
        and rule.localizable
        and rule.currently_user_visible
        and rule.required_locales
        and _is_long_form(rule.field_path)
    }

    # This is not a shortcut around translation work. M02-E only translates
    # descriptions that current product surfaces actually render. When a
    # future surface promotes any long-form field to required, this assertion
    # intentionally fails so that the same change must add zh-TW/en coverage.
    assert required == set()


def test_canonical_srd_long_text_exists_but_is_explicitly_deferred() -> None:
    registry = ContentRegistry.from_directory(DEFAULT_CONTENT_ROOT)
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)

    policy_rules = {
        (rule.kind, rule.field_path): rule
        for rule in policy.rules
        if _srd_rule_applies("srd5.1", rule.pack)
    }

    assert DEFERRED_SRD_LONG_FORM_RULES.issubset(policy_rules)

    for key in DEFERRED_SRD_LONG_FORM_RULES:
        rule = policy_rules[key]
        assert rule.localizable
        assert not rule.currently_user_visible
        assert rule.required_locales == ()

    # Prove that the zero required count is a product-surface decision rather
    # than an empty source dataset: SRD contains real long-form English text.
    spell = next(entry for entry in registry.list_kind("spell") if entry.data.get("desc"))
    condition = next(entry for entry in registry.list_kind("condition") if entry.data.get("desc"))
    item = next(entry for entry in registry.list_kind("item") if entry.data.get("desc"))

    assert spell.data["desc"]
    assert condition.data["desc"]
    assert item.data["desc"]


def test_deferred_long_text_never_creates_m02e_missing_translation_issues() -> None:
    from app.content.localization import ContentLocalizationCatalog

    registry = ContentRegistry.from_directory(DEFAULT_CONTENT_ROOT)
    policy = LocalizableFieldPolicy.from_path(POLICY_PATH)
    catalog = ContentLocalizationCatalog(registry, policy)

    for kind in ("spell", "condition", "item"):
        issues = catalog.completeness_issues(
            locales=("zh-TW",),
            sources={"srd5.1"},
            kinds={kind},
        )
        assert not any(_is_long_form(issue.field_path) for issue in issues)
