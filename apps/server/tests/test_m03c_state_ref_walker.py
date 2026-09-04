from __future__ import annotations

from app.interop.content_ref_walker import (
    STATE_REF_FIELD_NAMES,
    assert_no_unwalked_stable_keys,
    collect_state_refs,
)
from app.domain.character.schemas import CharacterState
from m03c_support import document


def test_state_ref_walker_collects_conditions_prepared_spells_and_inventory() -> None:
    payload = document("fixture_multiclass_mixed.json")["payload"]["current_state"]["state_payload"]
    refs = {ref.stable_key for ref in collect_state_refs(payload)}
    expected = {
        item["condition_ref"] for item in payload.get("conditions", [])
    }
    expected.update(item["spell_key"] for item in payload.get("prepared_spells", []))
    expected.update(item["item_ref"] for item in payload.get("inventory_state", []))
    assert expected <= refs


def test_state_ref_walker_audit_fails_fast_for_declared_unwalked_field() -> None:
    payload = {"future_ref": "srd5.1:condition:blinded"}
    try:
        assert_no_unwalked_stable_keys(
            payload,
            set(),
            root="state",
            field_names=STATE_REF_FIELD_NAMES | {"future_ref"},
        )
    except RuntimeError as exc:
        assert "future_ref" in str(exc)
    else:
        raise AssertionError("walker audit accepted an unwalked StableKey field")


def test_state_ref_walker_minimum_shape_has_no_refs() -> None:
    state = CharacterState(current_hp=1, conditions=[], inventory_state=[])
    assert collect_state_refs(state) == ()
