from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.content.schemas import ContentEntry


def _variant_entry(target_key: str, target_name: str = "Target") -> dict[str, object]:
    return {
        "key": "phb2014:race:test-variant",
        "index": "test-variant",
        "name": "Test Variant",
        "source": "phb2014",
        "ruleset": "dnd5e-2014",
        "data": {
            "index": "test-variant",
            "name": "Test Variant",
            "variant_of": {"key": target_key, "name": target_name},
        },
    }


def test_variant_of_accepts_same_kind_cross_source_reference() -> None:
    entry = ContentEntry.model_validate(
        _variant_entry("srd5.1:race:human", "Human")
    )

    assert entry.data["variant_of"]["key"] == "srd5.1:race:human"


@pytest.mark.parametrize(
    "target_key",
    [
        "srd5.1:spell:light",
        "srd5.1:subrace:high-elf",
    ],
)
def test_variant_of_rejects_wrong_kind_reference(target_key: str) -> None:
    with pytest.raises(ValidationError, match="variant_of must reference the same kind"):
        ContentEntry.model_validate(_variant_entry(target_key))


def test_variant_of_rejects_non_reference_payload() -> None:
    payload = _variant_entry("srd5.1:race:human", "Human")
    payload["data"]["variant_of"] = "srd5.1:race:human"  # type: ignore[index]

    with pytest.raises(ValidationError, match="variant_of must be a content reference"):
        ContentEntry.model_validate(payload)
