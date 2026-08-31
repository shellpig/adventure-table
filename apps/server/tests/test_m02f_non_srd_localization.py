from __future__ import annotations

from copy import deepcopy
import re

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import CONTENT_PACKS_ROOT


NON_SRD_SOURCES = {"phb2014", "scag", "gos"}
HAN = re.compile(r"[㐀-鿿]")


def _catalog():
    registry = load_default_content_registry()
    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)
    return registry, catalog


def test_m02f_non_srd_required_translation_scope_is_complete() -> None:
    _registry, catalog = _catalog()

    issues = catalog.completeness_issues(
        locales=("zh-TW",),
        sources=NON_SRD_SOURCES,
    )

    assert issues == (), "missing M02-F zh-TW fields: " + ", ".join(
        f"{issue.key}::{issue.field_path}" for issue in issues[:20]
    )


def test_m02f_shipped_required_names_and_roleplay_are_traditional_chinese() -> None:
    registry, catalog = _catalog()
    findings: list[str] = []

    for source in sorted(NON_SRD_SOURCES):
        for kind in ("race", "subrace", "background", "feature"):
            for entry in registry.list_kind(kind, source=source):
                if catalog.policy.is_required(source, kind, "name", "zh-TW"):
                    localized = catalog.resolve_name(entry.key, "zh-TW")
                    if (
                        localized.missing_required
                        or not isinstance(localized.value, str)
                        or not HAN.search(localized.value)
                    ):
                        findings.append(f"{entry.key}::name -> {localized.value!r}")

                feature = entry.data.get("feature")
                if (
                    kind == "background"
                    and isinstance(feature, dict)
                    and isinstance(feature.get("name"), str)
                    and catalog.policy.is_required(
                        source, kind, "data.feature.name", "zh-TW"
                    )
                ):
                    localized = catalog.resolve_field(
                        entry.key, "data.feature.name", "zh-TW"
                    )
                    if (
                        localized.missing_required
                        or not isinstance(localized.value, str)
                        or not HAN.search(localized.value)
                    ):
                        findings.append(
                            f"{entry.key}::data.feature.name -> {localized.value!r}"
                        )

                if kind == "background":
                    for suggestion in catalog.roleplay_suggestions(entry.key, "zh-TW"):
                        if suggestion.missing_required or not HAN.search(suggestion.text):
                            findings.append(
                                f"{entry.key}::{suggestion.suggestion_id} -> {suggestion.text!r}"
                            )

    assert findings == [], "M02-F source-language leakage: " + ", ".join(findings[:20])


def test_phb_variant_roleplay_reuses_parent_translation_with_child_identity() -> None:
    _registry, catalog = _catalog()

    parent = catalog.roleplay_suggestions("phb2014:background:criminal", "zh-TW")
    child = catalog.roleplay_suggestions("phb2014:background:spy", "zh-TW")

    assert [item.text for item in child] == [item.text for item in parent]
    assert child[0].suggestion_id.startswith("phb2014:background:spy:roleplay:")
    assert parent[0].suggestion_id.startswith("phb2014:background:criminal:roleplay:")
    assert child[0].suggestion_id != parent[0].suggestion_id


def test_scag_roleplay_inheritance_reuses_phb_translation_with_scag_identity() -> None:
    _registry, catalog = _catalog()

    parent = catalog.roleplay_suggestions("phb2014:background:soldier", "zh-TW")
    child = catalog.roleplay_suggestions("scag:background:city-watch", "zh-TW")

    assert [item.text for item in child] == [item.text for item in parent]
    assert child[0].suggestion_id.startswith("scag:background:city-watch:roleplay:")
    assert child[0].suggestion_id != parent[0].suggestion_id


def test_scag_explicit_roleplay_does_not_get_replaced_by_inheritance() -> None:
    _registry, catalog = _catalog()

    suggestions = catalog.roleplay_suggestions("scag:background:far-traveler", "zh-TW")

    assert len(suggestions) == 4
    assert suggestions[0].text == "我會把新見到的習俗與故鄉傳統相比較。"
    assert all(item.suggestion_id.startswith("scag:background:far-traveler:") for item in suggestions)


def test_m02f_localization_does_not_mutate_canonical_content_or_english() -> None:
    registry = load_default_content_registry()
    watched = {
        key: deepcopy(registry.get(key).model_dump(mode="python"))
        for key in (
            "phb2014:race:human-variant",
            "phb2014:background:spy",
            "scag:background:city-watch",
            "gos:background:shipwright",
        )
    }

    catalog = load_content_localization_catalog(registry, CONTENT_PACKS_ROOT)

    assert catalog.resolve_name("phb2014:race:human-variant", "en").value == "Variant Human"
    assert catalog.resolve_name("scag:background:city-watch", "en").value == "City Watch"
    assert catalog.resolve_name("gos:background:shipwright", "en").value == "Shipwright"
    assert catalog.resolve_name("phb2014:race:human-variant", "zh-TW").value == "變體人類"
    assert catalog.resolve_name("scag:background:city-watch", "zh-TW").value == "城市守衛"
    assert catalog.resolve_name("gos:background:shipwright", "zh-TW").value == "船工"

    for key, before in watched.items():
        assert registry.get(key).model_dump(mode="python") == before


def test_cross_pack_srd_reference_presentation_remains_owned_by_srd_overlay() -> None:
    registry, catalog = _catalog()
    city_watch = registry.get("scag:background:city-watch")
    first_proficiency = city_watch.data["starting_proficiencies"][0]

    assert first_proficiency["key"].startswith("srd5.1:")
    localized = catalog.resolve_name(first_proficiency["key"], "zh-TW")
    assert localized.value != first_proficiency["name"]
    assert HAN.search(str(localized.value))
