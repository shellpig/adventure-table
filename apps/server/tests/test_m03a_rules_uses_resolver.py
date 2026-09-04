from __future__ import annotations

import json
from pathlib import Path

import pytest

import app.domain.character_builder.rules as rules_module
from app.paths import resolve_rules_path


def _write_rules_variant(source: Path, target: Path, first_standard_score: int) -> Path:
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["ability_generation"]["standard_array"][0] = first_standard_score
    target.write_text(json.dumps(payload), encoding="utf-8")
    return target


def test_default_rules_path_is_resolved_at_call_time_and_cache_is_path_keyed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = resolve_rules_path()
    first = _write_rules_variant(source, tmp_path / "first.json", 16)
    second = _write_rules_variant(source, tmp_path / "second.json", 17)
    current = first

    rules_module.load_ability_generation_rules.cache_clear()
    monkeypatch.setattr(rules_module, "resolve_rules_path", lambda: current)

    assert rules_module.load_ability_generation_rules().standard_array[0] == 16
    current = second
    assert rules_module.load_ability_generation_rules().standard_array[0] == 17


def test_explicit_rules_path_still_overrides_default_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = resolve_rules_path()
    explicit = _write_rules_variant(source, tmp_path / "explicit.json", 18)
    rules_module.load_ability_generation_rules.cache_clear()
    monkeypatch.setattr(
        rules_module,
        "resolve_rules_path",
        lambda: (_ for _ in ()).throw(AssertionError("default resolver should not run")),
    )

    assert rules_module.load_ability_generation_rules(explicit).standard_array[0] == 18


def test_spellcasting_rules_use_the_same_runtime_resolver(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = resolve_rules_path()
    payload = json.loads(source.read_text(encoding="utf-8"))
    payload["spellcasting"]["classes"]["srd5.1:class:wizard"]["spellbook_initial"] = 7
    target = tmp_path / "spell-rules.json"
    target.write_text(json.dumps(payload), encoding="utf-8")

    rules_module.load_spellcasting_rules.cache_clear()
    monkeypatch.setattr(rules_module, "resolve_rules_path", lambda: target)

    loaded = rules_module.load_spellcasting_rules()
    assert loaded.classes["srd5.1:class:wizard"].spellbook_initial == 7
