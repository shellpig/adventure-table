from __future__ import annotations

import pytest

from app.config import Settings


DEFAULT_PACKS = (
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


def _clear_m03_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "DATABASE_URL",
        "ADVENTURE_TABLE_CONTENT_ROOT",
        "ADVENTURE_TABLE_DATABASE_PATH",
        "ADVENTURE_TABLE_SPA_ROOT",
        "ADVENTURE_TABLE_ENABLED_CONTENT_PACKS",
    ):
        monkeypatch.delenv(name, raising=False)


def test_settings_model_config_does_not_enable_env_prefix() -> None:
    assert not Settings.model_config.get("env_prefix")


def test_default_enabled_pack_set_matches_current_runtime(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_m03_env(monkeypatch)

    settings = Settings(_env_file=None)
    assert settings.enabled_content_packs == DEFAULT_PACKS


def test_enabled_pack_csv_is_trimmed_and_not_json_decoded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_m03_env(monkeypatch)
    monkeypatch.setenv(
        "ADVENTURE_TABLE_ENABLED_CONTENT_PACKS",
        " srd5.1, phb2014 ,mtf ",
    )

    settings = Settings(_env_file=None)
    assert settings.enabled_content_packs == ("srd5.1", "phb2014", "mtf")


def test_empty_enabled_pack_env_falls_back_to_full_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_m03_env(monkeypatch)
    monkeypatch.setenv("ADVENTURE_TABLE_ENABLED_CONTENT_PACKS", " , , ")

    settings = Settings(_env_file=None)
    assert settings.enabled_content_packs == DEFAULT_PACKS


def test_existing_database_url_environment_contract_is_preserved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_m03_env(monkeypatch)
    value = "postgresql+psycopg://user:pass@example.invalid:5432/adventure"
    monkeypatch.setenv("DATABASE_URL", value)

    settings = Settings(_env_file=None)
    assert settings.database_url == value


def test_m03_path_environment_aliases_are_read_without_env_prefix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _clear_m03_env(monkeypatch)
    monkeypatch.setenv("ADVENTURE_TABLE_CONTENT_ROOT", "/tmp/content")
    monkeypatch.setenv("ADVENTURE_TABLE_DATABASE_PATH", "/tmp/adventure.sqlite3")
    monkeypatch.setenv("ADVENTURE_TABLE_SPA_ROOT", "/tmp/web")
    monkeypatch.setenv("ADVENTURE_TABLE_ENABLED_CONTENT_PACKS", "srd5.1,mtf")

    settings = Settings(_env_file=None)
    assert settings.content_root == "/tmp/content"
    assert settings.database_path == "/tmp/adventure.sqlite3"
    assert settings.spa_root == "/tmp/web"
    assert settings.enabled_content_packs == ("srd5.1", "mtf")
