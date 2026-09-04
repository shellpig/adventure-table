"""Single source of truth for the frozen M03-A start content baseline.

`docs/M03/baseline/m03a-start.json` is the checked-in snapshot every M03
subphase compares against. Tests read it from here instead of repeating the
pack list or the entry counts inline.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASELINE_PATH = (
    Path(__file__).resolve().parents[3] / "docs" / "M03" / "baseline" / "m03a-start.json"
)


def _load() -> dict[str, Any]:
    with BASELINE_PATH.open(encoding="utf-8") as handle:
        return json.load(handle)


_BASELINE = _load()

M03A_START_PACKS: tuple[str, ...] = tuple(_BASELINE["enabled_content_packs"])
M03A_START_PACK_ENTRY_COUNTS: dict[str, int] = dict(_BASELINE["pack_entry_counts"])
M03A_START_ENTRY_COUNT: int = int(_BASELINE["total_entries"])

assert tuple(M03A_START_PACK_ENTRY_COUNTS) == M03A_START_PACKS
assert sum(M03A_START_PACK_ENTRY_COUNTS.values()) == M03A_START_ENTRY_COUNT
