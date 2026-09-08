from app.api.meta import build_capabilities


def test_web_channel_advertises_p2_multiplayer_capabilities() -> None:
    snapshot = build_capabilities("web")

    assert snapshot.capabilities.room is True
    assert snapshot.capabilities.campaign is True
    assert snapshot.capabilities.seat is True
    assert snapshot.capabilities.session is True


def test_standalone_channel_keeps_multiplayer_capabilities_disabled() -> None:
    snapshot = build_capabilities("standalone")

    assert snapshot.capabilities.room is False
    assert snapshot.capabilities.campaign is False
    assert snapshot.capabilities.seat is False
    assert snapshot.capabilities.session is False
