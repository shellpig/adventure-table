from __future__ import annotations

from fastapi import APIRouter, Depends

from app.api.dependencies import get_content_registry
from app.api.errors import APIError
from app.content.identity import URL_ROUTE_TO_KIND, parse_stable_key
from app.content.registry import ContentNotFoundError, ContentRegistry
from app.content.schemas import ContentEntry

router = APIRouter(prefix="/api/rules/content", tags=["rules-content"])


def _kind_for_category(category: str) -> str:
    kind = URL_ROUTE_TO_KIND.get(category)
    if kind is None:
        raise APIError(404, "unknown_reference", f"unknown reference category: {category}")
    return kind


@router.get("/{category}", response_model=list[ContentEntry])
def list_content(
    category: str,
    registry: ContentRegistry = Depends(get_content_registry),
) -> list[ContentEntry]:
    return list(registry.list_kind(_kind_for_category(category)))


@router.get("/{category}/{key}", response_model=ContentEntry)
def get_content(
    category: str,
    key: str,
    registry: ContentRegistry = Depends(get_content_registry),
) -> ContentEntry:
    kind = _kind_for_category(category)
    try:
        if ":" in key:
            parsed = parse_stable_key(key, kinds={kind})
            return registry.get(f"{parsed.source}:{parsed.kind}:{parsed.index}")
        # Bare index is retained only as a legacy SRD compatibility route.
        return registry.resolve("srd5.1", kind, key)
    except (ContentNotFoundError, ValueError) as exc:
        raise APIError(404, "unknown_reference", f"unknown content reference: {key}") from exc
