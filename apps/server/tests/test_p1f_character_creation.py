from __future__ import annotations

from typing import Any

from fastapi.testclient import TestClient
from sqlalchemy import create_engine, event, func, select
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.db import metadata
from app.domain.character_builder.service import CharacterBuilderService
from app.main import app
from app.persistence.builder_drafts import BuilderDraftRepository, character_build_drafts
from app.persistence.characters import (
    CharacterRepository,
    characters,
    character_states,
    character_versions,
)


DIRECT_SOURCES = {
    "content:race",
    "content:background",
    "content:alignment",
    "content:subrace",
    "content:subclass",
    "content:class",
    "builder:ability-generation",
    "equipment",
}


def _seed(*, raise_server_exceptions: bool = True):
    registry = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    character_repository = CharacterRepository(engine, registry)
    app.state.content_registry = registry
    app.state.character_engine = engine
    app.state.character_repository = character_repository
    app.state.character_builder_service = CharacterBuilderService(
        BuilderDraftRepository(engine),
        registry,
        character_repository,
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), engine


def _create_fighter_draft(client: TestClient) -> dict[str, Any]:
    response = client.post(
        "/api/character-builder/drafts",
        json={
            "draft_payload": {
                "basic": {"name": "P1-F Fighter"},
                "target_level": 1,
                "race_selection": {"reference_id": "srd5.1:race:human"},
                "background_selection": {
                    "reference_id": "srd5.1:background:acolyte"
                },
                "ability_generation": {
                    "method": "standard_array",
                    "scores": {
                        "strength": 15,
                        "dexterity": 14,
                        "constitution": 13,
                        "intelligence": 12,
                        "wisdom": 10,
                        "charisma": 8,
                    },
                    "provenance": "test",
                },
                "level_choices": [
                    {
                        "character_level": 1,
                        "class_ref": "srd5.1:class:fighter",
                        "hp_method": "first_level",
                        "hp_base_gain": 10,
                    }
                ],
            }
        },
    )
    assert response.status_code == 201
    return response.json()


def _selected_generic_refs(view: dict[str, Any]) -> set[str]:
    selections = view["draft"]["draft_payload"].get("choice_selections") or {}
    choices = {choice["choice_id"]: choice for choice in view["choices"]}
    result: set[str] = set()
    for choice_id, selection in selections.items():
        choice = choices.get(choice_id)
        if not choice:
            continue
        options = {option["option_id"]: option for option in choice["options"]}
        for selected_id in selection.get("selected_option_ids", []):
            option = options.get(selected_id)
            if (
                option
                and option.get("reference_id")
                and option.get("category") != "ability_bonus"
            ):
                result.add(option["reference_id"])
    return result


def _fill_generic_choices(client: TestClient, view: dict[str, Any]) -> dict[str, Any]:
    draft_id = view["draft"]["id"]
    for _ in range(12):
        selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
        used_refs = _selected_generic_refs(view)
        changed = False

        for choice in view["choices"]:
            if (
                not choice["required"]
                or choice.get("disabled_reason")
                or choice.get("option_source") in DIRECT_SOURCES
            ):
                continue
            current = selections.get(choice["choice_id"], {}).get(
                "selected_option_ids", []
            )
            if len(current) == choice["choose_count"]:
                continue

            selected: list[str] = []
            for option in choice["options"]:
                if option.get("disabled_reason"):
                    continue
                reference_id = option.get("reference_id")
                if (
                    reference_id
                    and option.get("category") != "ability_bonus"
                    and reference_id in used_refs
                ):
                    continue
                selected.append(option["option_id"])
                if reference_id and option.get("category") != "ability_bonus":
                    used_refs.add(reference_id)
                if len(selected) == choice["choose_count"]:
                    break

            if len(selected) < choice["choose_count"] and choice.get("allow_duplicates"):
                legal = [
                    option
                    for option in choice["options"]
                    if not option.get("disabled_reason")
                ]
                while legal and len(selected) < choice["choose_count"]:
                    selected.append(legal[0]["option_id"])

            assert len(selected) == choice["choose_count"], choice["label"]
            selections[choice["choice_id"]] = {
                "choice_id": choice["choice_id"],
                "source_ref": choice.get("source_ref"),
                "selected_option_ids": selected,
            }
            changed = True

        if not changed:
            return view

        response = client.patch(
            f"/api/character-builder/drafts/{draft_id}",
            json={
                "expected_revision": view["draft"]["revision"],
                "draft_payload": {"choice_selections": selections},
            },
        )
        assert response.status_code == 200, response.text
        view = response.json()
    raise AssertionError("generic builder choices did not converge")


def _equipment_selection(raw: Any) -> list[str]:
    if isinstance(raw, str):
        return [raw]
    if isinstance(raw, list):
        return [value for value in raw if isinstance(value, str)]
    if isinstance(raw, dict):
        nested = raw.get("selected_option_ids")
        if isinstance(nested, list):
            return [value for value in nested if isinstance(value, str)]
    return []


def _fill_equipment_choices(client: TestClient, view: dict[str, Any]) -> dict[str, Any]:
    draft_id = view["draft"]["id"]
    for _ in range(12):
        selections = dict(
            view["draft"]["draft_payload"].get("starting_equipment_choices") or {}
        )
        changed = False
        for choice in view["choices"]:
            if choice.get("option_source") != "equipment" or choice.get(
                "disabled_reason"
            ):
                continue
            current = _equipment_selection(selections.get(choice["choice_id"]))
            if len(current) == choice["choose_count"]:
                continue
            legal = [
                option
                for option in choice["options"]
                if not option.get("disabled_reason")
            ]
            selected = [option["option_id"] for option in legal[: choice["choose_count"]]]
            assert len(selected) == choice["choose_count"], choice["label"]
            selections[choice["choice_id"]] = selected
            changed = True

        if not changed:
            return view

        response = client.patch(
            f"/api/character-builder/drafts/{draft_id}",
            json={
                "expected_revision": view["draft"]["revision"],
                "draft_payload": {"starting_equipment_choices": selections},
            },
        )
        assert response.status_code == 200, response.text
        view = response.json()
    raise AssertionError("equipment choices did not converge")


def _complete_fighter_draft(client: TestClient) -> dict[str, Any]:
    view = _create_fighter_draft(client)
    view = _fill_generic_choices(client, view)
    return _fill_equipment_choices(client, view)


def _count(engine, table) -> int:
    with engine.connect() as connection:
        value = connection.scalar(select(func.count()).select_from(table))
    return int(value or 0)


def test_p1f_review_confirm_is_idempotent_and_inventory_stays_live_state() -> None:
    client, engine = _seed()
    view = _complete_fighter_draft(client)
    draft_id = view["draft"]["id"]

    review = client.get(f"/api/character-builder/drafts/{draft_id}/review")
    assert review.status_code == 200, review.text
    review_payload = review.json()
    assert review_payload["can_confirm"] is True, review_payload["issues"]
    assert review_payload["build_candidate"]["starting_equipment"]
    assert review_payload["starting_equipment"]
    assert review_payload["initial_state"]["current_hp"] > 0
    assert review_payload["initial_state"]["temporary_hp"] == 0
    assert review_payload["initial_state"]["conditions"] == []
    assert review_payload["initial_state"]["inventory_state"]

    confirmed = client.post(f"/api/character-builder/drafts/{draft_id}/confirm")
    assert confirmed.status_code == 200, confirmed.text
    result = confirmed.json()
    character_id = result["character_id"]
    assert result["version_no"] == 1
    assert result["character_path"] == f"/characters/{character_id}"

    repeated = client.post(f"/api/character-builder/drafts/{draft_id}/confirm")
    assert repeated.status_code == 200
    assert repeated.json()["character_id"] == character_id
    assert _count(engine, characters) == 1
    assert _count(engine, character_versions) == 1
    assert _count(engine, character_states) == 1

    with engine.connect() as connection:
        version = connection.execute(
            select(
                character_versions.c.version_kind,
                character_versions.c.parent_version_id,
                character_versions.c.superseded_by_version_id,
                character_versions.c.change_note,
            )
        ).mappings().one()
    assert version["version_kind"] == "create"
    assert version["parent_version_id"] is None
    assert version["superseded_by_version_id"] is None
    assert version["change_note"] is None

    character = client.get(f"/api/characters/{character_id}").json()
    build_inventory_count = len(character["build"]["starting_equipment"])
    live_inventory = character["state"]["inventory_state"]
    assert len(live_inventory) == build_inventory_count
    assert build_inventory_count > 1

    mutated_inventory = live_inventory[1:]
    patched = client.patch(
        f"/api/characters/{character_id}/state",
        json={"inventory_state": mutated_inventory},
    )
    assert patched.status_code == 200, patched.text

    repeated_after_mutation = client.post(
        f"/api/character-builder/drafts/{draft_id}/confirm"
    )
    assert repeated_after_mutation.status_code == 200
    reloaded = client.get(f"/api/characters/{character_id}").json()
    assert len(reloaded["build"]["starting_equipment"]) == build_inventory_count
    assert reloaded["state"]["inventory_state"] == mutated_inventory

    active_drafts = client.get("/api/character-builder/drafts").json()
    assert all(item["draft"]["id"] != draft_id for item in active_drafts)

    engine.dispose()


def test_p1f_blocked_confirm_and_database_failure_leave_no_partial_character() -> None:
    client, engine = _seed(raise_server_exceptions=False)

    incomplete = _create_fighter_draft(client)
    blocked = client.post(
        f"/api/character-builder/drafts/{incomplete['draft']['id']}/confirm"
    )
    assert blocked.status_code == 422
    assert _count(engine, characters) == 0
    assert _count(engine, character_versions) == 0
    assert _count(engine, character_states) == 0

    client.delete(f"/api/character-builder/drafts/{incomplete['draft']['id']}")
    complete = _complete_fighter_draft(client)
    draft_id = complete["draft"]["id"]

    def fail_state_insert(conn, cursor, statement, parameters, context, executemany):
        if statement.lstrip().upper().startswith("INSERT INTO CHARACTER_STATES"):
            raise RuntimeError("forced P1-F transaction failure")

    event.listen(engine, "before_cursor_execute", fail_state_insert)
    try:
        failed = client.post(f"/api/character-builder/drafts/{draft_id}/confirm")
        assert failed.status_code == 500
    finally:
        event.remove(engine, "before_cursor_execute", fail_state_insert)

    assert _count(engine, characters) == 0
    assert _count(engine, character_versions) == 0
    assert _count(engine, character_states) == 0
    with engine.connect() as connection:
        confirmed_character_id = connection.scalar(
            select(character_build_drafts.c.confirmed_character_id).where(
                character_build_drafts.c.id == draft_id
            )
        )
    assert confirmed_character_id is None

    retry = client.post(f"/api/character-builder/drafts/{draft_id}/confirm")
    assert retry.status_code == 200, retry.text
    assert _count(engine, characters) == 1

    engine.dispose()
