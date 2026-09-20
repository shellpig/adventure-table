from __future__ import annotations

from datetime import datetime, timezone
from typing import cast
from uuid import UUID, uuid4

from app.domain.adventures.payloads import dump_entry_payload, parse_entry_payload
from app.domain.adventures.schemas import (
    AdventureArchivedError,
    AdventureDefinition,
    AdventureDefinitionCreate,
    AdventureDefinitionPatch,
    AdventureEntry,
    AdventureEntryCreate,
    AdventureEntryKind,
    AdventureEntryNotFoundError,
    AdventureEntryParentError,
    AdventureEntryPatch,
    AdventureEntryReorder,
    AdventureEntryVisibility,
    AdventureForbiddenError,
    AdventureNotFoundError,
    AdventureStatus,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.adventures.repository import (
    UNSET,
    AdventureRepository,
    StoredAdventureDefinition,
    StoredAdventureEntry,
)


def _to_definition_view(stored: StoredAdventureDefinition) -> AdventureDefinition:
    return AdventureDefinition(
        id=stored.id,
        room_id=stored.room_id,
        name=stored.name,
        summary=stored.summary,
        ruleset=stored.ruleset,
        status=cast(AdventureStatus, stored.status),
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )


def _to_entry_view(stored: StoredAdventureEntry) -> AdventureEntry:
    parsed_data = parse_entry_payload(stored.kind, stored.data_json)
    return AdventureEntry(
        id=stored.id,
        adventure_id=stored.adventure_id,
        parent_entry_id=stored.parent_entry_id,
        kind=cast(AdventureEntryKind, stored.kind),
        title=stored.title,
        body=stored.body,
        data=parsed_data,
        visibility=cast(AdventureEntryVisibility, stored.visibility),
        sort_order=stored.sort_order,
        provenance=stored.provenance_json,
        source_ref=stored.source_ref_json,
        created_at=stored.created_at,
        updated_at=stored.updated_at,
    )


class AdventureService:
    def __init__(self, repository: AdventureRepository) -> None:
        self.repository = repository

    @staticmethod
    def _require_author(context: RoomAccessContext, room_id: UUID) -> None:
        if context.room_id != room_id:
            raise AdventureNotFoundError(f"Room {room_id} not found")
        if context.authority is RoomAccessAuthority.MEMBER:
            raise AdventureForbiddenError("Owner or DM authority is required")

    def _definition_or_404(self, room_id: UUID, adventure_id: UUID) -> StoredAdventureDefinition:
        definition = self.repository.get_definition(room_id, adventure_id)
        if definition is None:
            raise AdventureNotFoundError(f"Adventure {adventure_id} not found in room {room_id}")
        return definition

    def _writable_definition(self, room_id: UUID, adventure_id: UUID) -> StoredAdventureDefinition:
        definition = self._definition_or_404(room_id, adventure_id)
        if definition.status == "archived":
            raise AdventureArchivedError(f"Adventure {adventure_id} is archived")
        return definition

    def _validate_parent(
        self,
        adventure_id: UUID,
        parent_entry_id: UUID | None,
        entry_id: UUID | None = None,
    ) -> None:
        if parent_entry_id is None:
            return
        if entry_id is not None and parent_entry_id == entry_id:
            raise AdventureEntryParentError("An entry cannot be its own parent")

        parent = self.repository.get_entry(adventure_id, parent_entry_id)
        if parent is None:
            raise AdventureEntryParentError(
                f"Parent entry {parent_entry_id} not found in adventure {adventure_id}"
            )

        if entry_id is not None:
            current_parent_id = parent.parent_entry_id
            visited: set[UUID] = {parent.id}
            while current_parent_id is not None:
                if current_parent_id == entry_id:
                    raise AdventureEntryParentError(
                        f"Setting parent creates a cycle: {entry_id} is an ancestor"
                    )
                if current_parent_id in visited:
                    break
                visited.add(current_parent_id)
                ancestor = self.repository.get_entry(adventure_id, current_parent_id)
                if ancestor is None:
                    break
                current_parent_id = ancestor.parent_entry_id

    def create_definition(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        payload: AdventureDefinitionCreate,
    ) -> AdventureDefinition:
        self._require_author(context, room_id)
        now = datetime.now(timezone.utc)
        definition_id = uuid4()
        stored = StoredAdventureDefinition(
            id=definition_id,
            room_id=room_id,
            name=payload.name,
            summary=payload.summary,
            ruleset=payload.ruleset,
            status="draft",
            created_at=now,
            updated_at=now,
        )
        self.repository.insert_definition(stored)
        return _to_definition_view(stored)

    def get_definition(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        adventure_id: UUID,
    ) -> AdventureDefinition:
        self._require_author(context, room_id)
        stored = self._definition_or_404(room_id, adventure_id)
        return _to_definition_view(stored)

    def list_definitions(
        self,
        context: RoomAccessContext,
        room_id: UUID,
    ) -> list[AdventureDefinition]:
        self._require_author(context, room_id)
        stored_list = self.repository.list_definitions(room_id)
        return [_to_definition_view(stored) for stored in stored_list]

    def patch_definition(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        adventure_id: UUID,
        payload: AdventureDefinitionPatch,
    ) -> AdventureDefinition:
        self._require_author(context, room_id)
        self._writable_definition(room_id, adventure_id)
        now = datetime.now(timezone.utc)
        updated = self.repository.update_definition(
            adventure_id,
            name=payload.name,
            summary=payload.summary if "summary" in payload.model_fields_set else UNSET,
            updated_at=now,
        )
        if updated is None:
            raise AdventureNotFoundError(f"Adventure {adventure_id} not found in room {room_id}")
        return _to_definition_view(updated)

    def create_entry(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        adventure_id: UUID,
        payload: AdventureEntryCreate,
    ) -> AdventureEntry:
        self._require_author(context, room_id)
        self._writable_definition(room_id, adventure_id)

        parsed_payload = parse_entry_payload(payload.kind, payload.data)
        dumped_data = dump_entry_payload(parsed_payload)

        if payload.parent_entry_id is not None:
            self._validate_parent(adventure_id, payload.parent_entry_id, entry_id=None)

        sort_order = (
            payload.sort_order
            if payload.sort_order is not None
            else self.repository.next_sort_order(adventure_id)
        )
        entry_id = uuid4()
        now = datetime.now(timezone.utc)
        stored = StoredAdventureEntry(
            id=entry_id,
            adventure_id=adventure_id,
            parent_entry_id=payload.parent_entry_id,
            kind=payload.kind,
            title=payload.title,
            body=payload.body,
            data_json=dumped_data,
            visibility=payload.visibility,
            sort_order=sort_order,
            provenance_json=None,
            source_ref_json=None,
            created_at=now,
            updated_at=now,
        )
        self.repository.insert_entry(stored)
        return _to_entry_view(stored)

    def get_entry(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        adventure_id: UUID,
        entry_id: UUID,
    ) -> AdventureEntry:
        self._require_author(context, room_id)
        self._definition_or_404(room_id, adventure_id)
        stored = self.repository.get_entry(adventure_id, entry_id)
        if stored is None:
            raise AdventureEntryNotFoundError(
                f"Adventure entry {entry_id} not found in adventure {adventure_id}"
            )
        return _to_entry_view(stored)

    def list_entries(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        adventure_id: UUID,
    ) -> list[AdventureEntry]:
        self._require_author(context, room_id)
        self._definition_or_404(room_id, adventure_id)
        stored_list = self.repository.list_entries(adventure_id)
        return [_to_entry_view(stored) for stored in stored_list]

    def patch_entry(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        adventure_id: UUID,
        entry_id: UUID,
        payload: AdventureEntryPatch,
    ) -> AdventureEntry:
        self._require_author(context, room_id)
        self._writable_definition(room_id, adventure_id)

        existing = self.repository.get_entry(adventure_id, entry_id)
        if existing is None:
            raise AdventureEntryNotFoundError(
                f"Adventure entry {entry_id} not found in adventure {adventure_id}"
            )

        dumped_data: dict[str, object] | None = None
        if payload.data is not None:
            dumped_data = dump_entry_payload(parse_entry_payload(existing.kind, payload.data))

        if "parent_entry_id" in payload.model_fields_set:
            self._validate_parent(adventure_id, payload.parent_entry_id, entry_id=entry_id)

        now = datetime.now(timezone.utc)
        updated = self.repository.update_entry(
            adventure_id,
            entry_id,
            title=payload.title if "title" in payload.model_fields_set else UNSET,
            body=payload.body if "body" in payload.model_fields_set else UNSET,
            data_json=dumped_data,
            visibility=payload.visibility if "visibility" in payload.model_fields_set else None,
            parent_entry_id=(
                payload.parent_entry_id
                if "parent_entry_id" in payload.model_fields_set
                else UNSET
            ),
            updated_at=now,
        )
        if updated is None:
            raise AdventureEntryNotFoundError(f"Adventure entry {entry_id} not found")
        return _to_entry_view(updated)

    def delete_entry(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        adventure_id: UUID,
        entry_id: UUID,
    ) -> None:
        self._require_author(context, room_id)
        self._writable_definition(room_id, adventure_id)
        existing = self.repository.get_entry(adventure_id, entry_id)
        if existing is None:
            raise AdventureEntryNotFoundError(
                f"Adventure entry {entry_id} not found in adventure {adventure_id}"
            )
        self.repository.delete_entry(adventure_id, entry_id)

    def reorder_entries(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        adventure_id: UUID,
        payload: AdventureEntryReorder,
    ) -> None:
        self._require_author(context, room_id)
        self._writable_definition(room_id, adventure_id)
        success = self.repository.reorder_entries(adventure_id, payload.entry_ids)
        if not success:
            raise AdventureEntryNotFoundError("One or more entry IDs not found in adventure")


__all__ = ["AdventureService"]
