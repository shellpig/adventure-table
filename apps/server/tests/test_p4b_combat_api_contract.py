from __future__ import annotations

from fastapi import FastAPI
from sqlalchemy import create_engine
from starlette.requests import Request

from app.api.rooms.combat import _map_combat_error, router
from app.api.rooms.dependencies import (
    get_combat_initiative_service,
    get_combat_order_service,
    get_combat_service,
)
from app.content import load_default_content_registry
from app.domain.combat.initiative import CombatInitiativeService, InitiativeInputError
from app.domain.combat.lifecycle import CombatService, CombatStateConflictError
from app.domain.combat.order import CombatOrderService
from app.domain.rooms.table_events import TableEventActorUnauthorizedError


PREFIX = (
    "/api/rooms/{room_id}/campaigns/{campaign_id}"
    "/sessions/{session_id}/combat"
)


def test_combat_router_exposes_complete_p4b_http_surface() -> None:
    actual = {
        (route.path, method)
        for route in router.routes
        for method in (route.methods or set())
    }
    assert actual == {
        (PREFIX, "GET"),
        (f"{PREFIX}/start", "POST"),
        (f"{PREFIX}/entries/characters", "POST"),
        (f"{PREFIX}/entries/monsters", "POST"),
        (f"{PREFIX}/initiative/request", "POST"),
        (f"{PREFIX}/initiative/roll", "POST"),
        (f"{PREFIX}/initiative/suggested-order", "GET"),
        (f"{PREFIX}/initiative/ties", "GET"),
        (f"{PREFIX}/initiative/finalize", "POST"),
        (f"{PREFIX}/initiative/reorder", "POST"),
        (f"{PREFIX}/turn/advance", "POST"),
        (f"{PREFIX}/actions", "POST"),
        (f"{PREFIX}/reaction-window", "POST"),
        (f"{PREFIX}/entries/{{entry_id}}/withdraw", "POST"),
        (f"{PREFIX}/entries/{{entry_id}}/remove", "POST"),
        (f"{PREFIX}/end", "POST"),
    }


def test_combat_http_errors_have_stable_codes() -> None:
    unauthorized = _map_combat_error(TableEventActorUnauthorizedError("no"))
    assert unauthorized.status_code == 403
    assert unauthorized.code == "table_actor_unauthorized"

    conflict = _map_combat_error(CombatStateConflictError("wrong turn"))
    assert conflict.status_code == 409
    assert conflict.code == "combat_state_conflict"

    invalid = _map_combat_error(InitiativeInputError("bad initiative"))
    assert invalid.status_code == 422
    assert invalid.code == "invalid_initiative_input"


def test_combat_dependency_providers_construct_share_and_cache_services() -> None:
    engine = create_engine("sqlite+pysqlite://")
    app = FastAPI()
    app.state.character_engine = engine
    app.state.content_registry = load_default_content_registry()
    request = Request({"type": "http", "app": app})
    try:
        combat = get_combat_service(request)
        initiative = get_combat_initiative_service(request)
        order = get_combat_order_service(request)

        assert isinstance(combat, CombatService)
        assert isinstance(initiative, CombatInitiativeService)
        assert isinstance(order, CombatOrderService)
        assert get_combat_service(request) is combat
        assert get_combat_initiative_service(request) is initiative
        assert get_combat_order_service(request) is order
        assert initiative.combat_service is combat
        assert initiative.combat_repository is combat.repository
        assert order.combat_service is combat
        assert order.table_event_service is combat.table_event_service
    finally:
        engine.dispose()
