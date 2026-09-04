from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.api.meta as meta


def _app_for(channel: meta.DistributionChannel) -> FastAPI:
    app = FastAPI()
    app.include_router(meta.create_meta_router(channel))
    return app


def test_meta_router_factory_keeps_channels_isolated_in_one_process() -> None:
    web = TestClient(_app_for("web")).get("/api/meta/capabilities").json()
    standalone = TestClient(_app_for("standalone")).get("/api/meta/capabilities").json()

    assert web["channel"] == "web"
    assert standalone["channel"] == "standalone"


def test_meta_module_exposes_factory_not_global_router() -> None:
    assert callable(meta.create_meta_router)
    assert not hasattr(meta, "meta_router")
    assert not hasattr(meta, "router")
