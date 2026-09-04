from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, Request, Response

from app.api.dependencies import get_character_repository
from app.interop.character_export import ExportChannel, build_character_export
from app.persistence.characters import CharacterRepository


router = APIRouter(prefix="/api/characters", tags=["characters"])


def _distribution_channel(request: Request) -> ExportChannel:
    value = getattr(request.app.state, "distribution_channel", "web")
    return "standalone" if value == "standalone" else "web"


@router.get("/{character_id}/export")
def export_character(
    character_id: UUID,
    request: Request,
    repository: CharacterRepository = Depends(get_character_repository),
) -> Response:
    artifact = build_character_export(
        repository,
        character_id,
        channel=_distribution_channel(request),
    )
    return Response(
        content=artifact.document.model_dump_json(indent=2),
        media_type="application/json",
        headers={
            "Content-Disposition": f'attachment; filename="{artifact.filename}"',
            "X-Adventure-Table-Character-Archived": str(artifact.archived).lower(),
        },
    )
