from __future__ import annotations

from uuid import uuid4

import pytest

from app.api.errors import APIError
from app.api.rooms.dependencies import _HistoryGuardedCharacterRepository


class _Delegate:
    def __init__(self) -> None:
        self.deleted = False

    def delete_character(self, _character_id) -> None:
        self.deleted = True


class _Campaigns:
    def __init__(self, referenced: bool) -> None:
        self.referenced = referenced

    def character_is_referenced(self, _character_id) -> bool:
        return self.referenced


class _Sessions:
    def __init__(self, referenced: bool) -> None:
        self.referenced = referenced

    def character_is_history_referenced(self, _character_id) -> bool:
        return self.referenced


def test_session_history_blocks_individual_character_delete_with_stable_error() -> None:
    delegate = _Delegate()
    repository = _HistoryGuardedCharacterRepository(
        delegate,
        _Campaigns(False),
        _Sessions(True),
    )

    with pytest.raises(APIError) as exc_info:
        repository.delete_character(uuid4())

    assert exc_info.value.code == "character_history_referenced"
    assert delegate.deleted is False


def test_unreferenced_character_still_uses_neutral_delete_primitive() -> None:
    delegate = _Delegate()
    repository = _HistoryGuardedCharacterRepository(
        delegate,
        _Campaigns(False),
        _Sessions(False),
    )
    repository.delete_character(uuid4())
    assert delegate.deleted is True
