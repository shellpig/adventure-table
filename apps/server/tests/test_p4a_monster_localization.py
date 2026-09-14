from __future__ import annotations

from pathlib import Path
from typing import Any

from app.content.localization import ContentLocalizationCatalog, LocalizableFieldPolicy


POLICY_PATH = (
    Path(__file__).resolve().parents[3]
    / "data"
    / "localization"
    / "localizable-fields.json"
)
MONSTER_KEY = "srd5.1:monster:localization-fixture"

_MONSTER_PAYLOAD: dict[str, Any] = {
    "key": MONSTER_KEY,
    "source": "srd5.1",
    "name": "Localization Fixture",
    "data": {
        "special_abilities": [
            {"name": "Keen Senses", "desc": "Canonical special ability description."}
        ],
        "actions": [{"name": "Bite", "desc": "Canonical action description."}],
        "bonus_actions": [
            {"name": "Phase Step", "desc": "Canonical bonus action description."}
        ],
        "reactions": [{"name": "Parry", "desc": "Canonical reaction description."}],
        "legendary_actions": [
            {"name": "Tail Swipe", "desc": "Canonical legendary action description."}
        ],
    },
}

_REQUIRED_CONCRETE_PATHS = {
    "name",
    "data.special_abilities.0.name",
    "data.actions.0.name",
    "data.bonus_actions.0.name",
    "data.reactions.0.name",
    "data.legendary_actions.0.name",
}

_ZH_TW_LABELS = {
    "name": "在地化測試怪物",
    "data.special_abilities.0.name": "敏銳感官",
    "data.actions.0.name": "啃咬",
    "data.bonus_actions.0.name": "相位步",
    "data.reactions.0.name": "招架",
    "data.legendary_actions.0.name": "掃尾",
}


class _FixtureEntry:
    key = MONSTER_KEY

    def model_dump(self, *, mode: str) -> dict[str, Any]:
        assert mode == "python"
        return _MONSTER_PAYLOAD


class _FixtureRegistry:
    enabled_pack_ids = ("srd5.1",)

    def __init__(self) -> None:
        self.entry = _FixtureEntry()

    def get(self, key: str) -> _FixtureEntry:
        assert key == MONSTER_KEY
        return self.entry

    def list_kind(
        self,
        kind: str,
        *,
        source: str | None = None,
    ) -> tuple[_FixtureEntry, ...]:
        if kind == "monster" and source in {None, "srd5.1"}:
            return (self.entry,)
        return ()


def _policy() -> LocalizableFieldPolicy:
    return LocalizableFieldPolicy.from_path(POLICY_PATH)


def _catalog(
    *,
    overlays: dict[tuple[str, str], dict[str, dict[str, Any]]] | None = None,
) -> ContentLocalizationCatalog:
    return ContentLocalizationCatalog(
        _FixtureRegistry(),  # type: ignore[arg-type]
        _policy(),
        overlays=overlays,
    )


def test_monster_policy_requires_current_labels_but_defers_descriptions() -> None:
    policy = _policy()

    for field_path in _REQUIRED_CONCRETE_PATHS:
        assert policy.is_required("srd5.1", "monster", field_path, "en")
        assert policy.is_required("srd5.1", "monster", field_path, "zh-TW")

    for field_path in (
        "data.special_abilities.0.desc",
        "data.actions.0.desc",
        "data.bonus_actions.0.desc",
        "data.reactions.0.desc",
        "data.legendary_actions.0.desc",
    ):
        assert not policy.is_required("srd5.1", "monster", field_path, "zh-TW")


def test_monster_english_is_complete_but_zh_tw_fallback_is_not() -> None:
    catalog = _catalog()

    english_issues = catalog.completeness_issues(
        locales=("en",),
        sources={"srd5.1"},
        kinds={"monster"},
    )
    assert english_issues == ()

    zh_tw_issues = catalog.completeness_issues(
        locales=("zh-TW",),
        sources={"srd5.1"},
        kinds={"monster"},
    )
    assert {issue.field_path for issue in zh_tw_issues} == _REQUIRED_CONCRETE_PATHS
    assert {issue.locale for issue in zh_tw_issues} == {"zh-TW"}

    fallback = catalog.resolve_name(MONSTER_KEY, "zh-TW")
    assert fallback.value == "Localization Fixture"
    assert fallback.fallback_used is True
    assert fallback.missing_required is True


def test_explicit_zh_tw_monster_labels_clear_completeness_gate() -> None:
    catalog = _catalog(
        overlays={
            ("srd5.1", "zh-TW"): {
                MONSTER_KEY: _ZH_TW_LABELS,
            }
        }
    )

    assert catalog.completeness_issues(
        locales=("zh-TW",),
        sources={"srd5.1"},
        kinds={"monster"},
    ) == ()

    deferred_desc = catalog.resolve_field(
        MONSTER_KEY,
        "data.actions.0.desc",
        "zh-TW",
    )
    assert deferred_desc.fallback_used is True
    assert deferred_desc.missing_required is False
