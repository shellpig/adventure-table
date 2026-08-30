from __future__ import annotations

from app.domain.character_builder.equipment import _presentation_metadata


def test_equipment_bundle_exposes_stable_presentation_items() -> None:
    raw = {
        "option_type": "multiple",
        "items": [
            {
                "option_type": "counted_reference",
                "count": 2,
                "of": {
                    "index": "javelin",
                    "name": "Javelin",
                    "url": "/api/2014/equipment/javelin",
                },
            },
            {
                "option_type": "reference",
                "item": {
                    "index": "shield",
                    "name": "Shield",
                    "url": "/api/2014/equipment/shield",
                },
            },
            {
                "option_type": "choice",
                "choice": {"choose": 1, "from": {"option_set_type": "options_array", "options": []}},
            },
        ],
    }

    items, has_choice = _presentation_metadata(raw)

    assert [(item.reference_id, item.count) for item in items] == [
        ("srd5.1:equipment:javelin", 2),
        ("srd5.1:equipment:shield", 1),
    ]
    assert has_choice is True


def test_single_equipment_reference_keeps_its_quantity() -> None:
    items, has_choice = _presentation_metadata(
        {
            "option_type": "counted_reference",
            "count": 5,
            "of": {
                "index": "javelin",
                "name": "Javelin",
                "url": "/api/2014/equipment/javelin",
            },
        }
    )

    assert [(item.reference_id, item.count) for item in items] == [
        ("srd5.1:equipment:javelin", 5),
    ]
    assert has_choice is False
