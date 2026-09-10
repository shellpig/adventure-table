from __future__ import annotations

from uuid import uuid4

import pytest

from app.domain.rooms.ai_controller_tokens import (
    AIControllerTokenError,
    mint_ai_controller_token,
    parse_ai_controller_token,
    verify_ai_controller_secret,
)


def test_ai_token_is_opaque_high_entropy_and_round_trips_public_id() -> None:
    grant_id = uuid4()
    minted = mint_ai_controller_token(grant_id=grant_id)
    assert minted.plaintext.startswith(f"at_ai_{grant_id.hex}_")
    parsed = parse_ai_controller_token(minted.plaintext)
    assert parsed.grant_id == grant_id
    assert len(parsed.secret) >= 32
    assert verify_ai_controller_secret(parsed.secret, minted.secret_hash)


def test_ai_token_hash_rejects_wrong_secret() -> None:
    minted = mint_ai_controller_token()
    parsed = parse_ai_controller_token(minted.plaintext)
    assert not verify_ai_controller_secret(parsed.secret + "wrong", minted.secret_hash)


def test_ai_token_display_hint_does_not_contain_plaintext_secret() -> None:
    minted = mint_ai_controller_token()
    parsed = parse_ai_controller_token(minted.plaintext)
    assert minted.plaintext != minted.display_hint
    assert parsed.secret not in minted.display_hint
    assert len(minted.secret_hash) == 32


@pytest.mark.parametrize(
    "token",
    [
        "",
        "at_human_deadbeef_secret",
        "at_ai_not-a-uuid_secret",
        f"at_ai_{uuid4().hex}_short",
    ],
)
def test_ai_token_parser_rejects_malformed_values(token: str) -> None:
    with pytest.raises(AIControllerTokenError):
        parse_ai_controller_token(token)
