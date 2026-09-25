from __future__ import annotations

from typing import Annotated, Any, Literal, Self, Union, cast
from uuid import UUID

from pydantic import Field, model_validator

from app.domain.adventure_imports.schemas import (
    DraftWarning,
    ImportDraft,
)
from app.domain.adventure_imports.service import AdventureImportService
from app.domain.campaign_runtime.ai_tools import CampaignContextAIToolApplicationService
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.schemas import StrictModel


class TextSourceToolInput(StrictModel):
    source_kind: Literal["paste", "markdown"]
    text: str
    filename: str | None = None


class UrlSourceToolInput(StrictModel):
    source_kind: Literal["url"]
    url: str
    text: str | None = None
    excerpt: str | None = None
    title: str | None = None


class AssetSourceToolInput(StrictModel):
    source_kind: Literal["asset"]
    asset_id: UUID


class ImportAdventureSourceToolInput(StrictModel):
    import_id: UUID | None = None
    name: str | None = Field(default=None, min_length=1, max_length=160)
    source: Annotated[
        Union[TextSourceToolInput, UrlSourceToolInput, AssetSourceToolInput],
        Field(discriminator="source_kind"),
    ]

    @model_validator(mode="after")
    def _validate_name_when_import_id_missing(self) -> Self:
        if self.import_id is None and not self.name:
            raise ValueError("name is required when import_id is None")
        return self


class GetImportDraftToolInput(StrictModel):
    import_id: UUID


class UpdateImportDraftToolInput(StrictModel):
    import_id: UUID
    draft: ImportDraft
    warnings: list[DraftWarning] = Field(default_factory=list)
    expected_revision: int


class ResolveImportWarningToolInput(StrictModel):
    import_id: UUID
    warning_id: str
    resolution: str | None = None
    expected_revision: int


class AnswerImportQuestionToolInput(StrictModel):
    import_id: UUID
    question_id: str
    answer: str
    expected_revision: int


class FinalizeAdventureToolInput(StrictModel):
    import_id: UUID
    name: str = Field(min_length=1, max_length=160)
    summary: str | None = None
    expected_revision: int


class AdventureImportAIToolApplicationService(CampaignContextAIToolApplicationService):
    """Facade exposing AdventureImportService intents as transport-neutral MCP tools."""

    def __init__(
        self,
        *,
        adventure_import_service: AdventureImportService,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)
        self.adventure_import_service = adventure_import_service

    def import_adventure_source(
        self,
        token: str,
        input: ImportAdventureSourceToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        # A source that fails after the import was created leaves an empty import the DM can cancel.
        import_id = input.import_id or self.adventure_import_service.create_import(
            actor, actor.room_id, cast(str, input.name)
        ).id

        if isinstance(input.source, TextSourceToolInput):
            source = self.adventure_import_service.add_text_source(
                actor,
                actor.room_id,
                import_id,
                source_kind=input.source.source_kind,
                text=input.source.text,
                filename=input.source.filename,
            )
        elif isinstance(input.source, UrlSourceToolInput):
            source = self.adventure_import_service.add_url_source(
                actor,
                actor.room_id,
                import_id,
                url=input.source.url,
                text=input.source.text,
                excerpt=input.source.excerpt,
                title=input.source.title,
            )
        else:
            source = self.adventure_import_service.add_asset_source(
                actor,
                actor.room_id,
                import_id,
                asset_id=input.source.asset_id,
            )

        return {"import_id": str(import_id), "source": source.model_dump(mode="json")}

    def get_import_draft(
        self,
        token: str,
        input: GetImportDraftToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.adventure_import_service.get_draft(actor, actor.room_id, input.import_id)
        return view.model_dump(mode="json")

    def update_import_draft(
        self,
        token: str,
        input: UpdateImportDraftToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.adventure_import_service.update_draft(
            actor,
            actor.room_id,
            input.import_id,
            draft=input.draft,
            warnings=input.warnings,
            expected_revision=input.expected_revision,
        )
        return view.model_dump(mode="json")

    def resolve_import_warning(
        self,
        token: str,
        input: ResolveImportWarningToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.adventure_import_service.resolve_import_warning(
            actor,
            actor.room_id,
            input.import_id,
            warning_id=input.warning_id,
            resolution=input.resolution,
            expected_revision=input.expected_revision,
        )
        return view.model_dump(mode="json")

    def answer_import_question(
        self,
        token: str,
        input: AnswerImportQuestionToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.adventure_import_service.answer_import_question(
            actor,
            actor.room_id,
            input.import_id,
            question_id=input.question_id,
            answer=input.answer,
            expected_revision=input.expected_revision,
        )
        return view.model_dump(mode="json")

    def finalize_adventure(
        self,
        token: str,
        input: FinalizeAdventureToolInput,
        *,
        authenticated: AIControllerAuthView | None = None,
    ) -> dict[str, Any]:
        actor = self._actor(token, authenticated=authenticated)
        view = self.adventure_import_service.finalize_adventure(
            actor,
            actor.room_id,
            input.import_id,
            name=input.name,
            summary=input.summary,
            expected_revision=input.expected_revision,
        )
        return view.model_dump(mode="json")


__all__ = [
    "AdventureImportAIToolApplicationService",
    "AnswerImportQuestionToolInput",
    "AssetSourceToolInput",
    "FinalizeAdventureToolInput",
    "GetImportDraftToolInput",
    "ImportAdventureSourceToolInput",
    "ResolveImportWarningToolInput",
    "TextSourceToolInput",
    "UpdateImportDraftToolInput",
    "UrlSourceToolInput",
]
