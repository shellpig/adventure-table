from __future__ import annotations

from typing import Any, Literal
from uuid import UUID

from pydantic import Field

from app.domain.combat.lifecycle import (
    CombatNotFoundError,
    CombatService,
    CombatStateConflictError,
)
from app.domain.combat.sizes import resolve_entry_size
from app.domain.room_assets.service import RoomAssetService
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.domain.spatial.primitives import (
    BarrierSegment,
    Footprint,
    GridCell,
    can_occupy,
    footprint_for_size,
    occupied_cells,
)
from app.domain.spatial.targeting import BarrierView, BlockerKind
from app.domain.combat.sizes import resolve_entry_size
from app.persistence.combat.lifecycle import StoredCombat, StoredCombatEntry, actor_binding
from app.persistence.combat_boards.repository import (
    BoardDoorStateConflictError,
    BoardNotFoundError,
    CombatBoardRepository,
    StoredBoardDoor,
    StoredCombatBoard,
)


class CombatPlacementInvalidError(RuntimeError):
    """A placement or door update the board state rejects (HTTP 409 combat_placement_invalid)."""


class CombatBoardImageNotFoundError(LookupError):
    pass


class PlaceCombatantInput(StrictModel):
    anchor_x: int = Field(ge=0, le=200)
    anchor_y: int = Field(ge=0, le=200)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class UpdateDoorStateInput(StrictModel):
    state: Literal["open", "closed", "locked", "broken"]
    revealed: bool | None = None
    expected_runtime_revision: int = Field(ge=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class BoardPositionView(StrictModel):
    entry_id: UUID
    anchor_x: int
    anchor_y: int
    footprint_width: int
    footprint_height: int
    revision: int


class BoardWallView(StrictModel):
    x1: int
    y1: int
    x2: int
    y2: int


class BoardDoorView(StrictModel):
    door_id: UUID | None
    x1: int
    y1: int
    x2: int
    y2: int
    state: str
    revealed: bool


class BoardTerrainView(StrictModel):
    x: int
    y: int
    terrain_kind: str


class CombatBoardView(StrictModel):
    combat_id: UUID
    width_cells: int
    height_cells: int
    grid_pixel_size: int | None
    grid_offset_x: int | None
    grid_offset_y: int | None
    has_image: bool
    source_battle_map_id: UUID | None
    source_battle_map_revision: int | None
    runtime_revision: int
    walls: tuple[BoardWallView, ...]
    doors: tuple[BoardDoorView, ...]
    terrain: tuple[BoardTerrainView, ...]
    drawings: tuple[dict[str, Any], ...]
    positions: tuple[BoardPositionView, ...]


class CombatBoardService:
    """P5-A Combat board runtime: placement, door state, and actor-projected reads."""

    def __init__(
        self,
        *,
        board_repository: CombatBoardRepository,
        combat_service: CombatService,
        room_asset_service: RoomAssetService,
        table_event_service: TableEventService,
    ) -> None:
        self.board_repository = board_repository
        self.combat_service = combat_service
        self.room_asset_service = room_asset_service
        self.table_event_service = table_event_service

    # ------------------------------------------------------------------
    # shared helpers

    def _notify(self, actor: TableActorContext) -> None:
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)

    def _active_board(self, actor: TableActorContext) -> tuple[StoredCombat, StoredCombatBoard]:
        combat = self.combat_service.repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        if combat.mode != "tactical":
            raise CombatStateConflictError("Combat board is only available for Tactical Combat")
        board = self.board_repository.get_board(combat.id)
        if board is None:
            raise CombatNotFoundError(f"Combat {combat.id} has no board")
        return combat, board

    def _authorize_placement(self, actor: TableActorContext, entry: StoredCombatEntry) -> None:
        if actor.is_current_dm:
            return
        if entry.subject_kind != "character" or entry.character_id is None:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM places Monster combatants"
            )
        subject_seat_id = self.combat_service.repository.controlling_seat_for_character(
            campaign_id=actor.campaign_id, session_id=actor.session_id,
            character_id=entry.character_id,
        )
        if subject_seat_id is None or subject_seat_id not in actor.controlled_seat_ids:
            raise TableEventActorUnauthorizedError("You can only place combatants you control")

    def _barriers(
        self, board: StoredCombatBoard, combat_id: UUID
    ) -> tuple[tuple[BarrierSegment, ...], frozenset[GridCell]]:
        baseline = board.baseline
        walls = [
            BarrierSegment(x1=wall["x1"], y1=wall["y1"], x2=wall["x2"], y2=wall["y2"])
            for wall in baseline.get("walls", [])
        ]
        door_coords = {str(raw["id"]): raw for raw in baseline.get("doors", [])}
        for runtime_door in self.board_repository.list_doors(combat_id):
            coords = door_coords.get(str(runtime_door.door_id))
            if coords is None:
                continue
            # A non-open door blocks movement — hidden doors included. The unified
            # combat_placement_invalid error never reveals which barrier was hit.
            if runtime_door.state != "open":
                walls.append(BarrierSegment(
                    x1=coords["x1"], y1=coords["y1"], x2=coords["x2"], y2=coords["y2"]
                ))
        blocked = frozenset(
            GridCell(x=terrain["x"], y=terrain["y"])
            for terrain in baseline.get("terrain", [])
            if terrain.get("terrain_kind") == "blocked"
        )
        return tuple(walls), blocked

    def _entry_footprint(self, entry: StoredCombatEntry) -> Footprint:
        size = resolve_entry_size(
            entry,
            character_repository=self.combat_service.character_repository,
            monster_repository=self.combat_service.monster_repository,
            registry=self.combat_service.registry,
        )
        return footprint_for_size(size)

    def _occupied_by_others(self, combat_id: UUID, entry_id: UUID) -> frozenset[GridCell]:
        cells: set[GridCell] = set()
        for position in self.board_repository.list_positions(combat_id):
            if position.combat_entry_id == entry_id:
                continue
            other = self.combat_service.repository.get_entry(position.combat_entry_id)
            if other is None or other.status != "active":
                continue
            other_footprint = self._entry_footprint(other)
            cells.update(occupied_cells(position.anchor_x, position.anchor_y, other_footprint))
        return frozenset(cells)

    # ------------------------------------------------------------------
    # P5-C spatial targeting helpers (shared by attack and spell services)

    def entry_footprint_cells(self, entry: StoredCombatEntry) -> tuple[GridCell, ...]:
        """Occupied grid cells of one entry on its combat board."""
        position = self.board_repository.get_position(entry.id)
        if position is None:
            raise CombatStateConflictError("Combatant has no board position")
        footprint = self._entry_footprint(entry)
        return tuple(occupied_cells(position.anchor_x, position.anchor_y, footprint))

    def sight_barriers(self, combat_id: UUID) -> tuple[BarrierView, ...]:
        """Full-truth sight blockers: walls plus closed/locked doors.

        Open and broken doors never block sight. Hidden walls/doors keep
        their full-truth kind here; callers project them per audience via
        ``public_blocker_kind``.
        """
        board = self.board_repository.get_board(combat_id)
        if board is None:
            raise CombatStateConflictError("Tactical Combat has no board")
        baseline = board.baseline
        barriers: list[BarrierView] = []
        for wall in baseline.get("walls", []):
            barriers.append(
                BarrierView(
                    segment=BarrierSegment(
                        x1=wall["x1"], y1=wall["y1"], x2=wall["x2"], y2=wall["y2"]
                    ),
                    kind="hidden_wall" if wall.get("visibility") == "hidden" else "wall",
                )
            )
        door_coords = {str(raw["id"]): raw for raw in baseline.get("doors", [])}
        for runtime_door in self.board_repository.list_doors(combat_id):
            coords = door_coords.get(str(runtime_door.door_id))
            if coords is None or runtime_door.state in ("open", "broken"):
                continue
            hidden = coords.get("visibility") == "hidden"
            kind: BlockerKind = (
                "hidden_door"
                if hidden
                else "locked_door"
                if runtime_door.state == "locked"
                else "closed_door"
            )
            barriers.append(
                BarrierView(
                    segment=BarrierSegment(
                        x1=coords["x1"], y1=coords["y1"], x2=coords["x2"], y2=coords["y2"]
                    ),
                    kind=kind,
                )
            )
        return tuple(barriers)

    # ------------------------------------------------------------------
    # placement

    def _check_placement(
        self,
        *,
        board: StoredCombatBoard,
        combat_id: UUID,
        entry: StoredCombatEntry,
        anchor_x: int,
        anchor_y: int,
        error_message: str,
    ) -> None:
        """Shared placement legality check reused by place_position and reposition.

        Full-truth validation: bounds, blocked terrain, walls/doors (a barrier
        cutting through the footprint's interior), and overlap with other
        tokens. Raises CombatPlacementInvalidError with the caller's message.
        """
        footprint = self._entry_footprint(entry)
        walls, blocked = self._barriers(board, combat_id)
        occupied_by_others = self._occupied_by_others(combat_id, entry.id)
        if not can_occupy(
            anchor_x, anchor_y, footprint,
            width_cells=board.width_cells, height_cells=board.height_cells,
            blocked_cells=blocked, barriers=walls,
            occupied_by_others=occupied_by_others,
        ):
            raise CombatPlacementInvalidError(error_message)

    def place_position(
        self, actor: TableActorContext, entry_id: UUID, request: PlaceCombatantInput
    ) -> BoardPositionView:
        combat, board = self._active_board(actor)
        entry = self.combat_service.repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat.id:
            raise CombatNotFoundError(f"Combat entry {entry_id} was not found")
        if entry.status != "active":
            raise CombatStateConflictError("only active Combat entries can be placed")
        self._authorize_placement(actor, entry)
        existing = self.board_repository.get_position(entry_id)
        if combat.status == "running":
            if existing is not None:
                raise CombatPlacementInvalidError(
                    "entry is already placed; repositioning is not supported mid-combat"
                )
        elif combat.status != "initiative_pending":
            raise CombatStateConflictError(
                f"cannot place Combat entries while Combat is {combat.status}"
            )
        footprint = self._entry_footprint(entry)
        self._check_placement(
            board=board, combat_id=combat.id, entry=entry,
            anchor_x=request.anchor_x, anchor_y=request.anchor_y,
            error_message="placement is out of bounds, blocked, or overlapping",
        )
        hidden = entry.id in self.combat_service._hidden_entry_ids((entry,))
        stored = self.board_repository.upsert_position_with_event(
            binding=actor_binding(actor), combat_id=combat.id, entry_id=entry.id,
            anchor_x=request.anchor_x, anchor_y=request.anchor_y,
            footprint_width=footprint.width, footprint_height=footprint.height,
            idempotency_key=request.idempotency_key,
            visibility="dm_only" if hidden else "public",
        )
        self._notify(actor)
        return BoardPositionView(
            entry_id=stored.combat_entry_id, anchor_x=stored.anchor_x, anchor_y=stored.anchor_y,
            footprint_width=stored.footprint_width, footprint_height=stored.footprint_height,
            revision=stored.revision,
        )

    # ------------------------------------------------------------------
    # runtime doors

    def update_door_state(
        self, actor: TableActorContext, door_id: UUID, request: UpdateDoorStateInput
    ) -> BoardDoorView:
        combat, board = self._active_board(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError(
                "Only the current Session DM can change board door state"
            )
        stored_door: StoredBoardDoor | None = None
        for candidate in self.board_repository.list_doors(combat.id):
            if candidate.door_id == door_id:
                stored_door = candidate
                break
        if stored_door is None:
            raise CombatNotFoundError(f"Board door {door_id} was not found")
        revealed = request.revealed if request.revealed is not None else stored_door.revealed
        hidden_origin = self._door_is_hidden(board, door_id)
        try:
            updated = self.board_repository.update_door_state_with_event(
                binding=actor_binding(actor), combat_id=combat.id, door_id=door_id,
                state=request.state, revealed=revealed,
                expected_runtime_revision=request.expected_runtime_revision,
                idempotency_key=request.idempotency_key,
                visibility="dm_only" if (hidden_origin and not revealed) else "public",
                hidden_origin=hidden_origin,
            )
        except BoardDoorStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        except BoardNotFoundError as exc:
            raise CombatNotFoundError(str(exc)) from exc
        self._notify(actor)
        return self._door_view(board, updated, is_dm=True)

    @staticmethod
    def _door_is_hidden(board: StoredCombatBoard, door_id: UUID) -> bool:
        for raw in board.baseline.get("doors", []):
            if str(raw.get("id")) == str(door_id):
                return raw.get("visibility") == "hidden"
        return False

    # ------------------------------------------------------------------
    # reads

    def get_board(self, actor: TableActorContext) -> CombatBoardView:
        combat, board = self._active_board(actor)
        return self._project_board(combat, board, is_dm=actor.is_current_dm)

    def _project_board(
        self, combat: StoredCombat, board: StoredCombatBoard, *, is_dm: bool
    ) -> CombatBoardView:
        baseline = board.baseline
        runtime_doors = {
            door.door_id: door for door in self.board_repository.list_doors(combat.id)
        }
        entries = tuple(self.combat_service.repository.list_entries(combat.id))
        hidden_ids = (
            frozenset() if is_dm else self.combat_service._hidden_entry_ids(entries)
        )
        walls = [
            BoardWallView(x1=wall["x1"], y1=wall["y1"], x2=wall["x2"], y2=wall["y2"])
            for wall in baseline.get("walls", [])
            if is_dm or wall.get("visibility") != "hidden"
        ]
        doors: list[BoardDoorView] = []
        for raw in baseline.get("doors", []):
            door_id = UUID(str(raw["id"]))
            runtime = runtime_doors.get(door_id)
            state = runtime.state if runtime is not None else str(raw.get("state", "closed"))
            revealed = runtime.revealed if runtime is not None else False
            hidden_origin = raw.get("visibility") == "hidden"
            if hidden_origin and not revealed and not is_dm:
                # Players see an unrevealed hidden door as a plain wall — no id, no "hidden"
                # string. The DM keeps the door (with id) so it can be revealed or changed.
                walls.append(BoardWallView(x1=raw["x1"], y1=raw["y1"], x2=raw["x2"], y2=raw["y2"]))
                continue
            doors.append(self._door_view(
                board,
                StoredBoardDoor(
                    combat_id=combat.id, door_id=door_id, state=state,
                    revealed=revealed, created_at=board.created_at,
                ),
                is_dm=is_dm,
                coords=(raw["x1"], raw["y1"], raw["x2"], raw["y2"]),
                hidden_origin=hidden_origin,
            ))
        # Sort so wall order cannot leak which segments are hidden doors.
        walls.sort(key=lambda wall: (wall.x1, wall.y1, wall.x2, wall.y2))
        positions = [
            BoardPositionView(
                entry_id=position.combat_entry_id, anchor_x=position.anchor_x,
                anchor_y=position.anchor_y, footprint_width=position.footprint_width,
                footprint_height=position.footprint_height, revision=position.revision,
            )
            for position in self.board_repository.list_positions(combat.id)
            if position.combat_entry_id not in hidden_ids
        ]
        return CombatBoardView(
            combat_id=combat.id,
            width_cells=board.width_cells, height_cells=board.height_cells,
            grid_pixel_size=board.grid_pixel_size,
            grid_offset_x=board.grid_offset_x, grid_offset_y=board.grid_offset_y,
            has_image=board.image_asset_id is not None,
            source_battle_map_id=board.source_battle_map_id,
            source_battle_map_revision=board.source_battle_map_revision,
            runtime_revision=board.runtime_revision,
            walls=tuple(walls), doors=tuple(doors),
            terrain=tuple(
                BoardTerrainView(x=terrain["x"], y=terrain["y"], terrain_kind=terrain["terrain_kind"])
                for terrain in baseline.get("terrain", [])
            ),
            drawings=tuple(dict(drawing) for drawing in baseline.get("drawings", [])),
            positions=tuple(positions),
        )

    def _door_view(
        self,
        board: StoredCombatBoard,
        door: StoredBoardDoor,
        *,
        is_dm: bool,
        coords: tuple[int, int, int, int] | None = None,
        hidden_origin: bool | None = None,
    ) -> BoardDoorView:
        if coords is None or hidden_origin is None:
            for raw in board.baseline.get("doors", []):
                if str(raw.get("id")) == str(door.door_id):
                    coords = (raw["x1"], raw["y1"], raw["x2"], raw["y2"])
                    hidden_origin = raw.get("visibility") == "hidden"
                    break
        if coords is None:
            raise CombatNotFoundError(f"Board door {door.door_id} was not found")
        assert hidden_origin is not None
        return BoardDoorView(
            # Players never receive a hidden door's id — revealed hidden doors
            # project as doors without an id.
            door_id=door.door_id if (is_dm or not hidden_origin) else None,
            x1=coords[0], y1=coords[1], x2=coords[2], y2=coords[3],
            state=door.state, revealed=door.revealed,
        )

    def open_board_image(self, actor: TableActorContext) -> tuple[str, str, Any]:
        """Return (mime_type, filename, binary handle) for the frozen board image."""
        _combat, board = self._active_board(actor)
        if board.image_asset_id is None:
            raise CombatBoardImageNotFoundError("Combat board has no image")
        stored = self.room_asset_service.repository.get(actor.room_id, board.image_asset_id)
        if stored is None:
            raise CombatBoardImageNotFoundError("Combat board image was not found")
        handle = self.room_asset_service.storage.open(stored.storage_key)
        return stored.mime_type, stored.original_filename, handle


__all__ = [
    "BoardDoorView",
    "BoardPositionView",
    "BoardTerrainView",
    "BoardWallView",
    "CombatBoardImageNotFoundError",
    "CombatBoardService",
    "CombatBoardView",
    "CombatPlacementInvalidError",
    "PlaceCombatantInput",
    "UpdateDoorStateInput",
]
