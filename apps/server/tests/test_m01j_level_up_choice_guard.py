"""Level Up must be able to extend an M01-J subclass choice.

The guard used to accept only new choice ids prefixed ``level:<target>:``. Every
M01-J subclass choice is prefixed ``m01-j:`` and keeps one stable id whose
choose_total grows with class level, so Level Up rejected them outright with
"level_up cannot add non-level-up choice", and a subclass carrying a persistent
choice could be taken by Direct Create but never by levelling up.
"""

from __future__ import annotations

import pytest

from test_p1f_character_creation import _complete_fighter_draft, _seed  # noqa: F401


FIGHTER_REF = "srd5.1:class:fighter"
RUNE_KNIGHT = "tce:subclass:rune-knight"
RUNE_CARVER = "m01-j:tce:rune-knight:rune-carver"


def _confirm_level_one_fighter(client) -> str:
    view = _complete_fighter_draft(client)
    response = client.post(f"/api/character-builder/drafts/{view['draft']['id']}/confirm")
    assert response.status_code == 200, response.text
    return response.json()["character_id"]


def _patch(client, draft_id: str, revision: int, payload: dict) -> tuple[int, dict]:
    response = client.patch(
        f"/api/character-builder/drafts/{draft_id}",
        json={"expected_revision": revision, "draft_payload": payload},
    )
    return response.status_code, response.json()


def _level_up_to(client, character_id: str, target: int, subclass_ref: str | None):
    """Open a Level Up draft and add one class level, optionally with a subclass."""

    response = client.post(
        f"/api/character-builder/characters/{character_id}/drafts",
        json={"mode": "level_up"},
    )
    assert response.status_code == 201, response.text
    view = response.json()
    draft_id = view["draft"]["id"]

    levels = list(view["draft"]["draft_payload"]["level_choices"])
    levels.append(
        {
            "character_level": target,
            "class_ref": FIGHTER_REF,
            "hp_method": "fixed_average",
            "hp_base_gain": 6,
            "subclass_ref": subclass_ref,
        }
    )
    status, view = _patch(client, draft_id, view["draft"]["revision"], {"level_choices": levels})
    assert status == 200, view
    return draft_id, view


def _rune_options(view) -> list[str]:
    choice = next(
        (item for item in view["choices"] if item["choice_id"] == RUNE_CARVER),
        None,
    )
    assert choice is not None, "Rune Carver choice missing from the level-up draft"
    return [
        option["option_id"] for option in choice["options"] if not option["disabled_reason"]
    ]


def _merged(view, **selections) -> dict:
    """A patch keeps the whole choice map, so existing picks must be carried over."""

    current = dict(view["draft"]["draft_payload"]["choice_selections"] or {})
    current.update(selections)
    return {"choice_selections": current}


def _selection(options: list[str]) -> dict:
    return {
        "choice_id": RUNE_CARVER,
        "source_ref": RUNE_KNIGHT,
        "selected_option_ids": options,
    }


def test_level_up_can_take_a_subclass_choice() -> None:
    client, _engine = _seed()
    character_id = _confirm_level_one_fighter(client)
    for target in (2, 3):
        draft_id, view = _level_up_to(
            client, character_id, target, RUNE_KNIGHT if target == 3 else None
        )
        if target == 3:
            options = _rune_options(view)
            assert len(options) >= 2
            status, patched = _patch(
                client,
                draft_id,
                view["draft"]["revision"],
                _merged(view, **{RUNE_CARVER: _selection(options[:2])}),
            )
            assert status == 200, patched
            saved = patched["draft"]["draft_payload"]["choice_selections"][RUNE_CARVER]
            assert saved["selected_option_ids"] == options[:2]
        response = client.post(f"/api/character-builder/drafts/{draft_id}/confirm")
        assert response.status_code == 200, response.text

    character = client.get(f"/api/characters/{character_id}").json()
    assert character["build"]["character_level"] == 3
    assert RUNE_KNIGHT in {
        entry["subclass_ref"] for entry in character["build"]["subclasses"]
    }


def test_level_up_cannot_drop_an_earlier_subclass_pick() -> None:
    client, _engine = _seed()
    character_id = _confirm_level_one_fighter(client)
    for target in (2, 3):
        draft_id, view = _level_up_to(
            client, character_id, target, RUNE_KNIGHT if target == 3 else None
        )
        if target == 3:
            options = _rune_options(view)
            status, patched = _patch(
                client,
                draft_id,
                view["draft"]["revision"],
                _merged(view, **{RUNE_CARVER: _selection(options[:2])}),
            )
            assert status == 200, patched
            revision = patched["draft"]["revision"]

            # Swapping a locked-in rune is a retrain, not a level up.
            status, body = _patch(
                client,
                draft_id,
                revision,
                _merged(patched, **{RUNE_CARVER: _selection([options[0], options[2]])}),
            )
            assert status == 422, body
            assert "cannot drop earlier selections" in body["error"]["message"]

            # Clearing it silently is refused for the same reason.
            cleared = dict(patched["draft"]["draft_payload"]["choice_selections"])
            cleared.pop(RUNE_CARVER)
            status, body = _patch(client, draft_id, revision, {"choice_selections": cleared})
            assert status == 422, body
            assert "cannot drop earlier selections" in body["error"]["message"]

            status, patched = _patch(
                client,
                draft_id,
                revision,
                _merged(patched, **{RUNE_CARVER: _selection(options[:2])}),
            )
            assert status == 200, patched
        response = client.post(f"/api/character-builder/drafts/{draft_id}/confirm")
        assert response.status_code == 200, response.text


@pytest.mark.parametrize(
    "choice_id",
    ("equipment:fighter:deadbeefdead", "m01-i:fighter:optional-features"),
)
def test_level_up_still_rejects_unrelated_new_choices(choice_id: str) -> None:
    client, _engine = _seed()
    character_id = _confirm_level_one_fighter(client)
    draft_id, view = _level_up_to(client, character_id, 2, None)
    status, body = _patch(
        client,
        draft_id,
        view["draft"]["revision"],
        _merged(
            view,
            **{
                choice_id: {
                    "choice_id": choice_id,
                    "source_ref": None,
                    "selected_option_ids": ["srd5.1:language:elvish"],
                }
            },
        ),
    )
    assert status == 422, body
    assert "cannot add non-level-up choice" in body["error"]["message"]
