from __future__ import annotations

from typing import Literal

from fastapi import APIRouter
from pydantic import BaseModel, ConfigDict

from app.paths import resolve_database_path

DistributionChannel = Literal["web", "standalone"]


class CapabilityFlags(BaseModel):
    model_config = ConfigDict(extra="forbid")

    character_builder: bool = True
    character_import_export: bool = True
    room: bool = False
    campaign: bool = False
    session: bool = False
    seat: bool = False
    combat: bool = False
    timeline: bool = False
    ai_actor: bool = False


class Capabilities(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: DistributionChannel
    capabilities: CapabilityFlags
    database_path: str | None = None


def build_capabilities(channel: DistributionChannel) -> Capabilities:
    database_path = None
    if channel == "standalone":
        resolved = resolve_database_path()
        database_path = str(resolved) if resolved is not None else None
    return Capabilities(
        channel=channel,
        capabilities=CapabilityFlags(),
        database_path=database_path,
    )


def create_meta_router(channel: DistributionChannel) -> APIRouter:
    """Create a fresh router so web and standalone channel state cannot leak."""

    router = APIRouter(prefix="/api/meta", tags=["meta"])

    @router.get("/capabilities", response_model=Capabilities)
    def get_capabilities() -> Capabilities:
        return build_capabilities(channel)

    return router


__all__ = [
    "Capabilities",
    "CapabilityFlags",
    "DistributionChannel",
    "build_capabilities",
    "create_meta_router",
]
