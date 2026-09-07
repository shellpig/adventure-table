from __future__ import annotations

from typing import cast
from uuid import UUID

from sqlalchemy.engine import Connection, Engine

from app.content.registry import ContentRegistry
from app.domain.character.schemas import PersistedCharacter
from app.domain.character_builder.creation import BuilderConfirmResult
from app.domain.character_builder.schemas import (
    BuilderDraftCreateInput,
    BuilderDraftPatchInput,
    BuilderMode,
    BuilderValidationResult,
    BuilderView,
)
from app.domain.character_builder.service import CharacterBuilderService
from app.interop.character_import import CharacterImportResult, CharacterImportService
from app.interop.json_schema import CharacterExport
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository
from app.persistence.rooms.campaigns import CampaignRepository
from app.persistence.rooms.workspace import RoomWorkspaceRepository
from app.persistence.transaction_bound import TransactionBoundEngine


class RoomWorkspaceScopeError(PermissionError):
    pass


class RoomCharacterWorkspaceService:
    """Web-only namespace around the neutral Character/Builder/Interop services."""

    def __init__(
        self,
        engine: Engine,
        registry: ContentRegistry,
        *,
        workspace_repository: RoomWorkspaceRepository | None = None,
    ) -> None:
        self.engine = engine
        self.registry = registry
        self.workspace_repository = workspace_repository or RoomWorkspaceRepository(engine)
        self.character_repository = CharacterRepository(engine, registry)
        self.builder_repository = BuilderDraftRepository(engine)
        self.builder_service = CharacterBuilderService(
            self.builder_repository,
            registry,
            self.character_repository,
        )
        self.import_service = CharacterImportService(engine, registry)

    def _bound_services(
        self,
        connection: Connection,
    ) -> tuple[CharacterRepository, CharacterBuilderService, CharacterImportService]:
        # The core constructors intentionally continue to accept Engine. The cast
        # is localized here: TransactionBoundEngine supplies exactly begin/connect,
        # the only Engine surface these persistence services consume.
        bound_engine = cast(Engine, TransactionBoundEngine(connection))
        character_repository = CharacterRepository(bound_engine, self.registry)
        builder_repository = BuilderDraftRepository(bound_engine)
        return (
            character_repository,
            CharacterBuilderService(
                builder_repository,
                self.registry,
                character_repository,
            ),
            CharacterImportService(bound_engine, self.registry),
        )

    def require_character(self, room_id: UUID, character_id: UUID) -> None:
        if self.workspace_repository.character_room_id(character_id) != room_id:
            raise RoomWorkspaceScopeError(f"character {character_id} is not in Room {room_id}")

    def require_draft(self, room_id: UUID, draft_id: UUID) -> None:
        if self.workspace_repository.draft_room_id(draft_id) != room_id:
            raise RoomWorkspaceScopeError(f"draft {draft_id} is not in Room {room_id}")

    def set_character_archived(
        self,
        room_id: UUID,
        character_id: UUID,
        archived: bool,
    ) -> PersistedCharacter:
        with self.engine.begin() as connection:
            existing_room = self.workspace_repository.character_room_id_in_transaction(
                connection,
                character_id,
            )
            if existing_room != room_id:
                raise RoomWorkspaceScopeError(
                    f"character {character_id} is not in Room {room_id}"
                )
            character_repository, _, _ = self._bound_services(connection)
            character = character_repository.set_archived(character_id, archived)
            if character is None:
                raise RoomWorkspaceScopeError(
                    f"character {character_id} is not in Room {room_id}"
                )
            if archived:
                CampaignRepository.clear_character_seat_selections_in_transaction(
                    connection,
                    room_id=room_id,
                    character_id=character_id,
                )
            return character

    def create_draft(self, room_id: UUID, request: BuilderDraftCreateInput) -> BuilderView:
        with self.engine.begin() as connection:
            _, builder_service, _ = self._bound_services(connection)
            view = builder_service.create_draft(request)
            self.workspace_repository.attach_draft_in_transaction(
                connection,
                room_id=room_id,
                draft_id=view.draft.id,
            )
            return view

    def create_version_draft(
        self,
        room_id: UUID,
        character_id: UUID,
        mode: BuilderMode,
    ) -> BuilderView:
        with self.engine.begin() as connection:
            existing_room = self.workspace_repository.character_room_id_in_transaction(
                connection,
                character_id,
            )
            if existing_room != room_id:
                raise RoomWorkspaceScopeError(
                    f"character {character_id} is not in Room {room_id}"
                )
            _, builder_service, _ = self._bound_services(connection)
            view = builder_service.create_version_draft(character_id, mode)
            self.workspace_repository.attach_draft_in_transaction(
                connection,
                room_id=room_id,
                draft_id=view.draft.id,
            )
            return view

    def confirm_draft(self, room_id: UUID, draft_id: UUID) -> BuilderConfirmResult:
        with self.engine.begin() as connection:
            existing_room = self.workspace_repository.draft_room_id_in_transaction(
                connection,
                draft_id,
            )
            if existing_room != room_id:
                raise RoomWorkspaceScopeError(f"draft {draft_id} is not in Room {room_id}")
            _, builder_service, _ = self._bound_services(connection)
            draft = builder_service.get_draft(draft_id).draft
            result = builder_service.confirm_draft(draft_id)
            if draft.mode is BuilderMode.CREATE:
                self.workspace_repository.ensure_character_in_transaction(
                    connection,
                    room_id=room_id,
                    character_id=result.character_id,
                )
            else:
                character_room = self.workspace_repository.character_room_id_in_transaction(
                    connection,
                    result.character_id,
                )
                if character_room != room_id:
                    raise RoomWorkspaceScopeError(
                        f"confirmed character {result.character_id} left Room scope"
                    )
            return result.model_copy(
                update={
                    "character_path": f"/rooms/{room_id}/characters/{result.character_id}"
                }
            )

    def import_character(
        self,
        room_id: UUID,
        document: CharacterExport,
    ) -> CharacterImportResult:
        with self.engine.begin() as connection:
            _, _, import_service = self._bound_services(connection)
            result = import_service.commit(document)
            if result.character_id is not None:
                self.workspace_repository.attach_character_in_transaction(
                    connection,
                    room_id=room_id,
                    character_id=result.character_id,
                )
            if result.draft_id is not None:
                self.workspace_repository.attach_draft_in_transaction(
                    connection,
                    room_id=room_id,
                    draft_id=result.draft_id,
                )
            return result.model_copy(
                update={
                    "character_path": (
                        f"/rooms/{room_id}/characters/{result.character_id}"
                        if result.character_id is not None
                        else None
                    ),
                    "draft_path": (
                        f"/rooms/{room_id}/character-builder/{result.draft_id}"
                        if result.draft_id is not None
                        else None
                    ),
                }
            )

    def preview_import(self, document: CharacterExport) -> CharacterImportResult:
        return self.import_service.preview(document)

    def list_characters(
        self,
        room_id: UUID,
        *,
        archived: bool = False,
    ) -> tuple[PersistedCharacter, ...]:
        return tuple(
            self.character_repository.load_character(character_id)
            for character_id in self.workspace_repository.list_character_ids(
                room_id,
                archived=archived,
            )
        )

    def list_create_drafts(self, room_id: UUID) -> tuple[BuilderView, ...]:
        return tuple(
            self.builder_service.get_draft(draft_id)
            for draft_id in self.workspace_repository.list_draft_ids(
                room_id,
                create_only=True,
            )
        )

    def list_character_drafts(
        self,
        room_id: UUID,
        character_id: UUID,
    ) -> tuple[BuilderView, ...]:
        self.require_character(room_id, character_id)
        return tuple(
            self.builder_service.get_draft(draft_id)
            for draft_id in self.workspace_repository.list_draft_ids(
                room_id,
                character_id=character_id,
            )
        )

    def get_draft(self, room_id: UUID, draft_id: UUID) -> BuilderView:
        self.require_draft(room_id, draft_id)
        return self.builder_service.get_draft(draft_id)

    def patch_draft(
        self,
        room_id: UUID,
        draft_id: UUID,
        request: BuilderDraftPatchInput,
    ) -> BuilderView:
        self.require_draft(room_id, draft_id)
        return self.builder_service.patch_draft(draft_id, request)

    def validate_draft(self, room_id: UUID, draft_id: UUID) -> BuilderValidationResult:
        self.require_draft(room_id, draft_id)
        return self.builder_service.validate_draft(draft_id)

    def review_draft(self, room_id: UUID, draft_id: UUID):
        self.require_draft(room_id, draft_id)
        return self.builder_service.review_draft(draft_id)

    def cancel_draft(self, room_id: UUID, draft_id: UUID) -> None:
        self.require_draft(room_id, draft_id)
        self.builder_service.cancel_draft(draft_id)


__all__ = ["RoomCharacterWorkspaceService", "RoomWorkspaceScopeError"]
