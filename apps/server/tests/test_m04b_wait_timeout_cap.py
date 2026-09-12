from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.domain.rooms.ai_tools import WaitEventsInput


def test_mcp_wait_timeout_capped_to_preflight_value() -> None:
    assert WaitEventsInput(timeout=60).timeout == 60
    with pytest.raises(ValidationError):
        WaitEventsInput(timeout=60.001)
