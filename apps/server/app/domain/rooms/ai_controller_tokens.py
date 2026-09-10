from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
from uuid import UUID, uuid4


TOKEN_PREFIX = "at_ai_"
SECRET_BYTES = 32
DISPLAY_SECRET_CHARS = 6


class AIControllerTokenError(ValueError):
    pass


@dataclass(frozen=True)
class MintedAIControllerToken:
    grant_id: UUID
    plaintext: str
    secret_hash: bytes
    display_hint: str


@dataclass(frozen=True)
class ParsedAIControllerToken:
    grant_id: UUID
    secret: str


def hash_secret(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def mint_ai_controller_token(*, grant_id: UUID | None = None) -> MintedAIControllerToken:
    grant_id = grant_id or uuid4()
    secret = secrets.token_urlsafe(SECRET_BYTES)
    public_id = grant_id.hex
    plaintext = f"{TOKEN_PREFIX}{public_id}_{secret}"
    return MintedAIControllerToken(
        grant_id=grant_id,
        plaintext=plaintext,
        secret_hash=hash_secret(secret),
        display_hint=f"{TOKEN_PREFIX}{public_id}_{secret[:DISPLAY_SECRET_CHARS]}…",
    )


def parse_ai_controller_token(token: str) -> ParsedAIControllerToken:
    if not token.startswith(TOKEN_PREFIX):
        raise AIControllerTokenError("invalid AI controller token prefix")
    body = token[len(TOKEN_PREFIX) :]
    try:
        public_id, secret = body.split("_", 1)
        grant_id = UUID(hex=public_id)
    except (ValueError, AttributeError) as exc:
        raise AIControllerTokenError("malformed AI controller token") from exc
    if len(secret) < 16:
        raise AIControllerTokenError("malformed AI controller token secret")
    return ParsedAIControllerToken(grant_id=grant_id, secret=secret)


def verify_ai_controller_secret(secret: str, expected_hash: bytes) -> bool:
    return hmac.compare_digest(hash_secret(secret), expected_hash)


__all__ = [
    "AIControllerTokenError",
    "MintedAIControllerToken",
    "ParsedAIControllerToken",
    "hash_secret",
    "mint_ai_controller_token",
    "parse_ai_controller_token",
    "verify_ai_controller_secret",
]
