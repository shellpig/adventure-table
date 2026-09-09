from types import SimpleNamespace

from app.api.rooms import dependencies
from app.domain.rooms.character_rolls import CharacterRollModifierResolver


def test_p3c_web_dependencies_cache_services_and_share_roll_repository(monkeypatch) -> None:
    engine = object()
    registry = object()
    character_repository = object()
    event_repository = object()
    event_service = SimpleNamespace(repository=event_repository, notifier=None)
    workspace = SimpleNamespace(character_repository=character_repository)
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace()))

    monkeypatch.setattr(dependencies, "get_database_engine", lambda _request: engine)
    monkeypatch.setattr(dependencies, "get_content_registry", lambda _request: registry)
    monkeypatch.setattr(dependencies, "get_table_event_service", lambda _request: event_service)
    monkeypatch.setattr(dependencies, "get_room_workspace_service", lambda _request: workspace)

    roll_service = dependencies.get_roll_service(request)  # type: ignore[arg-type]
    pending_service = dependencies.get_pending_action_service(request)  # type: ignore[arg-type]

    assert dependencies.get_roll_service(request) is roll_service  # type: ignore[arg-type]
    assert dependencies.get_pending_action_service(request) is pending_service  # type: ignore[arg-type]
    assert pending_service.roll_repository is roll_service.repository
    assert isinstance(roll_service.modifier_resolver, CharacterRollModifierResolver)
    assert roll_service.modifier_resolver.character_repository is character_repository
    assert roll_service.modifier_resolver.registry is registry
