from __future__ import annotations

from pathlib import Path
import re


README = Path(__file__).resolve().parents[3] / "README.md"


def test_readme_documents_web_chat_oauth_deployment() -> None:
    text = README.read_text(encoding="utf-8")
    required = (
        "/mcp",
        "/.well-known/oauth-protected-resource",
        "/.well-known/oauth-authorization-server",
        "/mcp/oauth/register",
        "/mcp/oauth/authorize",
        "/mcp/oauth/token",
        "alembic upgrade web@head",
        "AI Seat",
        "AI Join Token",
    )
    for marker in required:
        assert marker in text


def test_readme_has_no_credentials() -> None:
    text = README.read_text(encoding="utf-8")
    assert "tskey-" not in text
    assert re.search(r"Bearer\s+at_", text) is None
    assert re.search(r"at_(?:oa|ai)_[A-Za-z0-9_-]{8,}", text) is None
