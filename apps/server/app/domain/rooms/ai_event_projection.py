from __future__ import annotations

import re

DICE_DETAIL_KEYS = frozenset({
    "raw_dice",
    "kept_dice",
    "base_modifier",
    "flat_adjustment",
    "source",
})

_SINGLE_KEPT_D20_PATTERN = re.compile(r"^(?:1d20|2d20k[hl]1)(?:[+-]\d+)?$")


def compact_roll_resolved(
    payload: dict[str, object],
    *,
    dc: int | None,
    auto_fail: bool,
    is_current_dm: bool,
) -> dict[str, object]:
    result: dict[str, object] = {
        key: value for key, value in payload.items() if key not in DICE_DETAIL_KEYS
    }

    natural: int | None = None
    kept_dice = payload.get("kept_dice")
    formula = payload.get("formula")
    if (
        isinstance(kept_dice, (list, tuple))
        and len(kept_dice) == 1
        and isinstance(kept_dice[0], int)
        and isinstance(formula, str)
        and bool(_SINGLE_KEPT_D20_PATTERN.match(formula))
    ):
        natural = kept_dice[0]

    result["natural"] = natural

    if is_current_dm:
        result["dc"] = dc
        outcome: str | None = None
        if dc is not None:
            total = payload["total"]
            assert isinstance(total, int)
            outcome = "failure" if auto_fail or total < dc else "success"
        result["outcome"] = outcome

    return result


__all__ = [
    "DICE_DETAIL_KEYS",
    "compact_roll_resolved",
]
