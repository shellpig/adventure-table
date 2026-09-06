from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import secrets
import threading
import time
from collections.abc import Callable


ROOM_CODE_ALPHABET = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
ROOM_CODE_LENGTH = 10
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
PASSWORD_HASH_BYTES = 64
SALT_BYTES = 32
SECRET_BYTES = 32
THROTTLE_WINDOW_SECONDS = 5 * 60
THROTTLE_MAX_FAILURES = 10


def generate_room_code() -> str:
    return "".join(secrets.choice(ROOM_CODE_ALPHABET) for _ in range(ROOM_CODE_LENGTH))


def normalize_room_code(value: str) -> str:
    code = value.strip().upper()
    if len(code) != ROOM_CODE_LENGTH or any(
        character not in ROOM_CODE_ALPHABET for character in code
    ):
        raise ValueError("room code must be 10 Crockford Base32 characters")
    return code


def generate_password_salt() -> bytes:
    return secrets.token_bytes(SALT_BYTES)


def hash_password(password: str, salt: bytes) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=SCRYPT_N,
        r=SCRYPT_R,
        p=SCRYPT_P,
        dklen=PASSWORD_HASH_BYTES,
    )


def verify_password(password: str, salt: bytes, expected_hash: bytes) -> bool:
    actual = hash_password(password, salt)
    return hmac.compare_digest(actual, expected_hash)


def generate_secret() -> str:
    return secrets.token_urlsafe(SECRET_BYTES)


def hash_secret(secret: str) -> bytes:
    return hashlib.sha256(secret.encode("utf-8")).digest()


def verify_secret(secret: str, expected_hash: bytes) -> bool:
    return hmac.compare_digest(hash_secret(secret), expected_hash)


@dataclass
class _Window:
    started_at: float
    failures: int


class FixedWindowThrottle:
    """Small process-local throttle for Room credential attempts."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        window_seconds: float = THROTTLE_WINDOW_SECONDS,
        max_failures: int = THROTTLE_MAX_FAILURES,
    ) -> None:
        self._clock = clock
        self._window_seconds = window_seconds
        self._max_failures = max_failures
        self._windows: dict[tuple[str, str], _Window] = {}
        self._lock = threading.Lock()

    def _current(self, key: tuple[str, str], now: float) -> _Window | None:
        window = self._windows.get(key)
        if window is not None and now - window.started_at >= self._window_seconds:
            self._windows.pop(key, None)
            return None
        return window

    def blocked(self, key: tuple[str, str]) -> bool:
        now = self._clock()
        with self._lock:
            window = self._current(key, now)
            return window is not None and window.failures >= self._max_failures

    def record_failure(self, key: tuple[str, str]) -> None:
        now = self._clock()
        with self._lock:
            window = self._current(key, now)
            if window is None:
                self._windows[key] = _Window(started_at=now, failures=1)
            else:
                window.failures += 1

    def clear(self, key: tuple[str, str]) -> None:
        with self._lock:
            self._windows.pop(key, None)


__all__ = [
    "FixedWindowThrottle",
    "ROOM_CODE_ALPHABET",
    "ROOM_CODE_LENGTH",
    "THROTTLE_MAX_FAILURES",
    "THROTTLE_WINDOW_SECONDS",
    "generate_password_salt",
    "generate_room_code",
    "generate_secret",
    "hash_password",
    "hash_secret",
    "normalize_room_code",
    "verify_password",
    "verify_secret",
]
