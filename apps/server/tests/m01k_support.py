"""M01-K shared fixtures with P2-B Room-aware Web HTTP support.

The domain/compiler fixtures remain unchanged in ``_m01k_support_core``.  This
module deliberately overrides only the real-Web HTTP boundary so every M01-K
consumer continues to exercise ``app.main`` after P2-B removes Web-global
Character routes.  Standalone coverage remains in the M03 standalone tests.
"""

from __future__ import annotations

from typing import Any

from _m01k_support_core import *  # noqa: F401,F403
from web_room_support import WebRoomTestClient, create_web_room_client, rebind_web_room_client


class M01KWebRoomClient(WebRoomTestClient):
    """Compatibility client that converts legacy M01-K URL literals to Room scope.

    Several M01-K matrix tests predate P2 and construct request URLs inline.  The
    shared fixture is the intended migration seam: no request leaves this client
    on a Web-global Character/Builder route.
    """

    def _room_scoped_url(self, url: str) -> str:
        if url == "/api/characters":
            return self.character_api
        if url.startswith("/api/characters/"):
            return f"{self.character_api}{url[len('/api/characters'):]}"
        if url == "/api/character-builder":
            return self.builder_api
        if url.startswith("/api/character-builder/"):
            return f"{self.builder_api}{url[len('/api/character-builder'):]}"
        return url

    def request(self, method, url, *args, **kwargs):  # type: ignore[override]
        return super().request(method, self._room_scoped_url(str(url)), *args, **kwargs)


def _client_for_context(
    room_id,
    access_token: str,
    *,
    raise_server_exceptions: bool = True,
) -> M01KWebRoomClient:
    return M01KWebRoomClient(
        room_id=room_id,
        access_token=access_token,
        raise_server_exceptions=raise_server_exceptions,
    )


def seed_http(*, raise_server_exceptions: bool = True):
    """Wire ``app.main`` to one fresh Owner Room on an in-memory database."""

    content = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    character_repository = CharacterRepository(engine, content)
    builder_service = CharacterBuilderService(
        BuilderDraftRepository(engine),
        content,
        character_repository,
    )
    base = create_web_room_client(
        engine,
        content,
        character_repository=character_repository,
        builder_service=builder_service,
        raise_server_exceptions=raise_server_exceptions,
        room_name="M01-K Web regression room",
    )
    setattr(engine, "_m01k_room_context", (base.room_id, base.access_token))
    return (
        _client_for_context(
            base.room_id,
            base.access_token,
            raise_server_exceptions=raise_server_exceptions,
        ),
        engine,
    )


def rebind_http(engine) -> M01KWebRoomClient:
    """Restart app-level services while preserving the exact Room/access session."""

    context = getattr(engine, "_m01k_room_context", None)
    if context is None:
        raise RuntimeError("M01-K restart requires a Room context created by seed_http()")
    room_id, access_token = context
    content = load_default_content_registry()
    rebind_web_room_client(
        engine,
        content,
        room_id=room_id,
        access_token=access_token,
    )
    return _client_for_context(room_id, access_token)


def http_create_draft(
    client: M01KWebRoomClient,
    draft_payload: dict[str, Any],
) -> dict[str, Any]:
    response = client.post(
        f"{client.builder_api}/drafts",
        json={"draft_payload": draft_payload},
    )
    assert response.status_code == 201, response.text
    return response.json()


def http_patch(
    client: M01KWebRoomClient,
    view: dict[str, Any],
    body: dict[str, Any],
    *,
    expect: int = 200,
) -> dict[str, Any]:
    response = client.patch(
        f"{client.builder_api}/drafts/{view['draft']['id']}",
        json={"expected_revision": view["draft"]["revision"], "draft_payload": body},
    )
    assert response.status_code == expect, response.text
    return response.json()


def http_fill_generic(
    client: M01KWebRoomClient,
    view: dict[str, Any],
    *,
    skip_sources: set[str] | None = None,
) -> dict[str, Any]:
    skip_sources = DIRECT_SOURCES | (skip_sources or set())
    draft_id = view["draft"]["id"]
    for _ in range(14):
        selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
        used_refs = http_selected_refs(view)
        changed = False
        for choice in view["choices"]:
            if (
                not choice["required"]
                or choice.get("disabled_reason")
                or choice.get("option_source") in skip_sources
            ):
                continue
            current = selections.get(choice["choice_id"], {}).get("selected_option_ids", [])
            if len(current) == choice["choose_count"]:
                continue
            picked: list[str] = []
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
                picked.append(option["option_id"])
                if reference_id and option.get("category") != "ability_bonus":
                    used_refs.add(reference_id)
                if len(picked) == choice["choose_count"]:
                    break
            if len(picked) < choice["choose_count"] and choice.get("allow_duplicates"):
                legal = [item for item in choice["options"] if not item.get("disabled_reason")]
                while legal and len(picked) < choice["choose_count"]:
                    picked.append(legal[0]["option_id"])
            assert len(picked) == choice["choose_count"], choice["label"]
            selections[choice["choice_id"]] = {
                "choice_id": choice["choice_id"],
                "source_ref": choice.get("source_ref"),
                "selected_option_ids": picked,
            }
            changed = True
        if not changed:
            return view
        response = client.patch(
            f"{client.builder_api}/drafts/{draft_id}",
            json={
                "expected_revision": view["draft"]["revision"],
                "draft_payload": {"choice_selections": selections},
            },
        )
        assert response.status_code == 200, response.text
        view = response.json()
    raise AssertionError("generic builder choices did not converge")


def http_fill_equipment(
    client: M01KWebRoomClient,
    view: dict[str, Any],
) -> dict[str, Any]:
    draft_id = view["draft"]["id"]
    for _ in range(12):
        selections = dict(view["draft"]["draft_payload"].get("starting_equipment_choices") or {})
        changed = False
        for choice in view["choices"]:
            if choice.get("option_source") != "equipment" or choice.get("disabled_reason"):
                continue
            current = selections.get(choice["choice_id"]) or []
            if isinstance(current, str):
                current = [current]
            if len(current) == choice["choose_count"]:
                continue
            legal = [item for item in choice["options"] if not item.get("disabled_reason")]
            picked = [item["option_id"] for item in legal[: choice["choose_count"]]]
            assert len(picked) == choice["choose_count"], choice["label"]
            selections[choice["choice_id"]] = picked
            changed = True
        if not changed:
            return view
        response = client.patch(
            f"{client.builder_api}/drafts/{draft_id}",
            json={
                "expected_revision": view["draft"]["revision"],
                "draft_payload": {"starting_equipment_choices": selections},
            },
        )
        assert response.status_code == 200, response.text
        view = response.json()
    raise AssertionError("equipment choices did not converge")


def http_confirm(
    client: M01KWebRoomClient,
    view: dict[str, Any],
    *,
    expect: int = 200,
) -> dict[str, Any]:
    response = client.post(
        f"{client.builder_api}/drafts/{view['draft']['id']}/confirm",
        json={"expected_revision": view["draft"]["revision"]},
    )
    assert response.status_code == expect, response.text
    return response.json()
