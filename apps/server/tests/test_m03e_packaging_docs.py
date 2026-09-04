from __future__ import annotations

from pathlib import Path
import tomllib


REPO_ROOT = Path(__file__).resolve().parents[3]


def test_standalone_extra_contains_pyinstaller_and_not_psycopg() -> None:
    data = tomllib.loads((REPO_ROOT / "apps/server/pyproject.toml").read_text(encoding="utf-8"))
    standalone = data["project"]["optional-dependencies"]["standalone"]

    assert any(item.startswith("pyinstaller") for item in standalone)
    assert all("psycopg" not in item for item in standalone)


def test_bilingual_readmes_cover_data_io_shutdown_and_unstable_schema() -> None:
    for name in ("README-standalone.en.txt", "README-standalone.zh-TW.txt"):
        text = (REPO_ROOT / name).read_text(encoding="utf-8").lower()
        assert "adventure-table.sqlite3" in text
        assert "json" in text
        assert "unstable" in text
        assert "ctrl+c" in text
        assert "browser" in text or "瀏覽器" in text


def test_distribution_notice_contains_srd_cc_by_attribution() -> None:
    text = (REPO_ROOT / "LICENSE.txt").read_text(encoding="utf-8")
    assert "Systems Reference Document 5.1" in text
    assert "CC BY 4.0" in text
