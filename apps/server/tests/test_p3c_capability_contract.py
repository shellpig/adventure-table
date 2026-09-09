from app.api.meta import build_capabilities


def test_p3c_roll_check_capability_is_web_only(monkeypatch) -> None:
    monkeypatch.setattr("app.api.meta.resolve_database_path", lambda: None)

    web = build_capabilities("web")
    standalone = build_capabilities("standalone")

    assert web.capabilities.table_runtime is True
    assert web.capabilities.roll_check is True
    assert standalone.capabilities.table_runtime is False
    assert standalone.capabilities.roll_check is False
