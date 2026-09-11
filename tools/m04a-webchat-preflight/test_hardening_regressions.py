from __future__ import annotations

import asyncio
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from server import Config, PreflightState, _parse_args, create_public_app  # noqa: E402
from test_server_contract import (  # noqa: E402
    _authorize_role,
    _form,
    _json,
    _request,
    _rpc,
)


@pytest.mark.parametrize(
    ("access_ttl_seconds", "refresh_ttl_seconds"),
    [(0, 60), (-1, 60), (60, 0), (60, -1)],
)
def test_config_rejects_non_positive_token_ttls(
    tmp_path: Path,
    access_ttl_seconds: int,
    refresh_ttl_seconds: int,
) -> None:
    with pytest.raises(ValueError, match="token TTL values must be positive"):
        Config(
            public_base_url="https://preflight.example",
            test_password="test-password",
            log_path=tmp_path / "preflight.jsonl",
            access_ttl_seconds=access_ttl_seconds,
            refresh_ttl_seconds=refresh_ttl_seconds,
        )


def test_refresh_rechecks_family_authority_inside_lock(tmp_path: Path) -> None:
    async def scenario() -> None:
        state = PreflightState()
        app = create_public_app(
            Config(
                public_base_url="https://preflight.example",
                test_password="test-password",
                log_path=tmp_path / "preflight.jsonl",
            ),
            state,
        )
        client_id, _, refresh_token = await _authorize_role(app, "dm")
        original_refresh_family = state.refresh_family

        def revoke_after_precheck(token: str | None):
            family = original_refresh_family(token)
            assert family is not None
            family.revoked = True
            return family

        state.refresh_family = revoke_after_precheck  # type: ignore[method-assign]
        status, _, body = await _request(
            app,
            method="POST",
            path="/token",
            body=_form(
                {
                    "grant_type": "refresh_token",
                    "client_id": client_id,
                    "refresh_token": refresh_token,
                }
            ),
            headers={"content-type": "application/x-www-form-urlencoded"},
        )
        assert status == 400
        assert _json(body)["error"] == "invalid_grant"

    asyncio.run(scenario())


def test_initialize_reports_hardened_server_version(tmp_path: Path) -> None:
    async def scenario() -> None:
        app = create_public_app(
            Config(
                public_base_url="https://preflight.example",
                test_password="test-password",
                log_path=tmp_path / "preflight.jsonl",
            )
        )
        _, access_token, _ = await _authorize_role(app, "dm")
        response = await _rpc(
            app,
            access_token,
            "initialize",
            {"protocolVersion": "2099-01-01"},
        )
        assert response["result"]["serverInfo"]["version"] == "0.2.0"

    asyncio.run(scenario())


def test_cli_token_ttl_overrides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "server.py",
            "--access-ttl-seconds",
            "17",
            "--refresh-ttl-seconds",
            "71",
        ],
    )
    args = _parse_args()
    assert args.access_ttl_seconds == 17
    assert args.refresh_ttl_seconds == 71
