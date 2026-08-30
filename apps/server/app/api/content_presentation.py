from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import get_content_localization
from app.api.errors import APIError
from app.content.localization import (
    DEFAULT_SERVER_PRESENTATION_LOCALE,
    ContentLocalizationCatalog,
    LocalizedRoleplaySuggestion,
    require_content_locale,
)
from app.content.registry import ContentNotFoundError, ContentValidationError


router = APIRouter(prefix="/api/rules/presentation", tags=["rules-content"])


class LocalizedFieldDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    field_path: str
    value: Any
    source: str
    fallback_used: bool
    missing_required: bool


class RoleplaySuggestionDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suggestion_id: str
    field: str
    position: int = Field(ge=0)
    text: str
    missing_required: bool


class ContentPresentationDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str
    locale: str
    fields: tuple[LocalizedFieldDTO, ...]
    roleplay_suggestions: tuple[RoleplaySuggestionDTO, ...] = ()


class ContentPresentationBatchRequest(BaseModel):
    """Resolve presentation for several StableKeys without leaking locale into domain DTOs."""

    model_config = ConfigDict(extra="forbid")

    references: tuple[str, ...] = Field(min_length=1, max_length=2000)
    fields: tuple[str, ...] = Field(default=("name",), min_length=1, max_length=20)


class ContentPresentationBatchDTO(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: str
    presentations: tuple[ContentPresentationDTO, ...]


def _suggestion_dto(value: LocalizedRoleplaySuggestion) -> RoleplaySuggestionDTO:
    return RoleplaySuggestionDTO(
        suggestion_id=value.suggestion_id,
        field=value.field,
        position=value.position,
        text=value.text,
        missing_required=value.missing_required,
    )


def _presentation_dto(
    localization: ContentLocalizationCatalog,
    key: str,
    locale: str,
    fields: tuple[str, ...],
) -> ContentPresentationDTO:
    localized_fields = tuple(
        localization.resolve_field(key, field_path, locale)
        for field_path in dict.fromkeys(fields)
    )
    roleplay = (
        localization.roleplay_suggestions(key, locale)
        if key.split(":", 2)[1:2] == ["background"]
        else ()
    )
    return ContentPresentationDTO(
        key=key,
        locale=locale,
        fields=tuple(
            LocalizedFieldDTO(
                field_path=value.field_path,
                value=value.value,
                source=value.source,
                fallback_used=value.fallback_used,
                missing_required=value.missing_required,
            )
            for value in localized_fields
        ),
        roleplay_suggestions=tuple(_suggestion_dto(value) for value in roleplay),
    )


@router.post("/batch", response_model=ContentPresentationBatchDTO)
def get_content_presentation_batch(
    request: ContentPresentationBatchRequest,
    locale: str = DEFAULT_SERVER_PRESENTATION_LOCALE,
    localization: ContentLocalizationCatalog = Depends(get_content_localization),
) -> ContentPresentationBatchDTO:
    """Batch presentation lookup used by Builder/Sheet localization overlays.

    StableKeys stay as the identity sent by the domain APIs. Locale only affects
    this presentation response, so switching languages cannot mutate a draft or
    character state.
    """

    try:
        locale = require_content_locale(locale)
        references = tuple(dict.fromkeys(request.references))
        fields = tuple(dict.fromkeys(request.fields))
        presentations = tuple(
            _presentation_dto(localization, key, locale, fields)
            for key in references
        )
    except (ContentNotFoundError, ContentValidationError, ValueError) as exc:
        raise APIError(404, "unknown_content_presentation", str(exc)) from exc

    return ContentPresentationBatchDTO(locale=locale, presentations=presentations)


@router.get("/{key}", response_model=ContentPresentationDTO)
def get_content_presentation(
    key: str,
    locale: str = DEFAULT_SERVER_PRESENTATION_LOCALE,
    field: list[str] = Query(default=["name"]),
    localization: ContentLocalizationCatalog = Depends(get_content_localization),
) -> ContentPresentationDTO:
    try:
        locale = require_content_locale(locale)
        if not field:
            raise ValueError("at least one presentation field is required")
        return _presentation_dto(localization, key, locale, tuple(field))
    except (ContentNotFoundError, ContentValidationError, ValueError) as exc:
        raise APIError(404, "unknown_content_presentation", str(exc)) from exc
