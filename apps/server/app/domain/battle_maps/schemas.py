from __future__ import annotations

from datetime import datetime
from typing import Literal, Self
from uuid import UUID

from pydantic import Field, field_validator, model_validator

from app.domain.rooms.schemas import StrictModel

BattleMapSourceKind = Literal["blank", "image"]
BattleMapWallVisibility = Literal["public", "hidden"]
BattleMapDoorState = Literal["open", "closed", "locked", "broken"]
BattleMapTerrainKind = Literal["normal", "difficult", "blocked"]
BattleMapAudience = Literal["dm", "player"]
BattleMapMonsterPlacementVisibility = Literal["public", "hidden"]

MAX_NAME_LENGTH = 160
MAX_DIMENSION_CELLS = 200
MAX_DRAWING_PAYLOAD_BYTES = 64 * 1024


class BattleMapWall(StrictModel):
    id: UUID
    x1: int
    y1: int
    x2: int
    y2: int
    visibility: BattleMapWallVisibility


class BattleMapDoor(StrictModel):
    id: UUID
    x1: int
    y1: int
    x2: int
    y2: int
    default_state: BattleMapDoorState
    visibility: BattleMapWallVisibility


class BattleMapTerrain(StrictModel):
    x: int
    y: int
    terrain_kind: BattleMapTerrainKind


class BattleMapDrawing(StrictModel):
    id: UUID
    payload: dict[str, object]


class BattleMapMonsterPlacement(StrictModel):
    """One monster pre-placement on a library map (M07-C)."""

    id: UUID
    template_key: str | None = None
    custom_template_id: UUID | None = None
    anchor_x: int
    anchor_y: int
    visibility: BattleMapMonsterPlacementVisibility
    sort_order: int


class BattleMap(StrictModel):
    id: UUID
    room_id: UUID
    name: str
    source_kind: BattleMapSourceKind
    image_asset_id: UUID | None
    width_cells: int
    height_cells: int
    grid_pixel_size: int | None
    grid_offset_x: int | None
    grid_offset_y: int | None
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None
    walls: list[BattleMapWall] = Field(default_factory=list)
    doors: list[BattleMapDoor] = Field(default_factory=list)
    terrain: list[BattleMapTerrain] = Field(default_factory=list)
    drawings: list[BattleMapDrawing] = Field(default_factory=list)
    # M07-C: monster pre-placements. Only present on management reads
    # (Human owner|dm get/copy/PUT, AI DM get_for_actor); never projected to Players.
    monster_placements: list[BattleMapMonsterPlacement] = Field(default_factory=list)


class MonsterPlacementInput(StrictModel):
    """One placement in a full-set replace. ``id`` is kept when supplied."""

    id: UUID | None = None
    template_key: str | None = None
    custom_template_id: UUID | None = None
    anchor_x: int
    anchor_y: int
    visibility: BattleMapMonsterPlacementVisibility = "public"
    sort_order: int = 0

    @model_validator(mode="after")
    def validate_single_template_source(self) -> Self:
        key = self.template_key.strip() if isinstance(self.template_key, str) else None
        has_key = bool(key)
        has_custom = self.custom_template_id is not None
        if has_key == has_custom:
            raise ValueError(
                "exactly one of template_key and custom_template_id must be set"
            )
        # Normalize so the service sees a canonical value.
        self.template_key = key if has_key else None
        return self


class MonsterPlacementsReplace(StrictModel):
    expected_revision: int = Field(gt=0)
    placements: list[MonsterPlacementInput] = Field(default_factory=list)


class MonsterPlacementProblem(StrictModel):
    placement_id: UUID
    code: str


class BattleMapSummary(StrictModel):
    id: UUID
    room_id: UUID
    name: str
    source_kind: BattleMapSourceKind
    image_asset_id: UUID | None
    width_cells: int
    height_cells: int
    revision: int
    created_at: datetime
    updated_at: datetime
    archived_at: datetime | None


class BattleMapCreate(StrictModel):
    name: str = Field(min_length=1, max_length=MAX_NAME_LENGTH)
    source_kind: BattleMapSourceKind
    image_asset_id: UUID | None = None
    width_cells: int = Field(ge=1, le=MAX_DIMENSION_CELLS)
    height_cells: int = Field(ge=1, le=MAX_DIMENSION_CELLS)
    grid_pixel_size: int | None = Field(default=None, gt=0)
    grid_offset_x: int | None = None
    grid_offset_y: int | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized


class BattleMapPatch(StrictModel):
    expected_revision: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)
    width_cells: int | None = Field(default=None, ge=1, le=MAX_DIMENSION_CELLS)
    height_cells: int | None = Field(default=None, ge=1, le=MAX_DIMENSION_CELLS)
    grid_pixel_size: int | None = Field(default=None, gt=0)
    grid_offset_x: int | None = None
    grid_offset_y: int | None = None

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized

    @model_validator(mode="after")
    def validate_at_least_one_mutation(self) -> Self:
        if not (self.model_fields_set - {"expected_revision"}):
            raise ValueError("at least one field must be set")
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        if "width_cells" in self.model_fields_set and self.width_cells is None:
            raise ValueError("width_cells cannot be null")
        if "height_cells" in self.model_fields_set and self.height_cells is None:
            raise ValueError("height_cells cannot be null")
        return self


class BattleMapWallInput(StrictModel):
    id: UUID | None = None
    x1: int
    y1: int
    x2: int
    y2: int
    visibility: BattleMapWallVisibility = "public"


class BattleMapDoorInput(StrictModel):
    id: UUID | None = None
    x1: int
    y1: int
    x2: int
    y2: int
    default_state: BattleMapDoorState = "closed"
    visibility: BattleMapWallVisibility = "public"


class BattleMapTerrainInput(StrictModel):
    x: int
    y: int
    terrain_kind: BattleMapTerrainKind


class BattleMapDrawingInput(StrictModel):
    id: UUID | None = None
    payload: dict[str, object]


class BattleMapObjectsReplace(StrictModel):
    expected_revision: int = Field(gt=0)
    walls: list[BattleMapWallInput] = Field(default_factory=list)
    doors: list[BattleMapDoorInput] = Field(default_factory=list)
    terrain: list[BattleMapTerrainInput] = Field(default_factory=list)
    drawings: list[BattleMapDrawingInput] = Field(default_factory=list)


class ProjectedBattleMapWall(StrictModel):
    """Player-safe wall: coordinates only, no id, no visibility."""

    x1: int
    y1: int
    x2: int
    y2: int


class ProjectedBattleMapDoor(StrictModel):
    """Player-safe public door: keeps id and state, never visibility."""

    id: UUID
    x1: int
    y1: int
    x2: int
    y2: int
    state: BattleMapDoorState


class ProjectedBattleMap(StrictModel):
    id: UUID
    room_id: UUID
    name: str
    source_kind: BattleMapSourceKind
    image_asset_id: UUID | None
    width_cells: int
    height_cells: int
    grid_pixel_size: int | None
    grid_offset_x: int | None
    grid_offset_y: int | None
    revision: int
    audience: BattleMapAudience
    walls: list[ProjectedBattleMapWall] = Field(default_factory=list)
    doors: list[ProjectedBattleMapDoor] = Field(default_factory=list)
    terrain: list[BattleMapTerrain] = Field(default_factory=list)
    drawings: list[BattleMapDrawing] = Field(default_factory=list)


class BattleMapCopy(StrictModel):
    expected_revision: int = Field(gt=0)
    name: str | None = Field(default=None, min_length=1, max_length=MAX_NAME_LENGTH)

    @field_validator("name")
    @classmethod
    def normalize_name(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.strip()
        if not normalized:
            raise ValueError("name cannot be blank")
        return normalized


class BattleMapArchive(StrictModel):
    expected_revision: int = Field(gt=0)


class TemporaryBattleMapInput(StrictModel):
    width_cells: int = Field(ge=1, le=MAX_DIMENSION_CELLS)
    height_cells: int = Field(ge=1, le=MAX_DIMENSION_CELLS)
    walls: list[BattleMapWallInput] = Field(default_factory=list)
    doors: list[BattleMapDoorInput] = Field(default_factory=list)
    terrain: list[BattleMapTerrainInput] = Field(default_factory=list)
    drawings: list[BattleMapDrawingInput] = Field(default_factory=list)


class BattleMapNotFoundError(Exception):
    pass


class BattleMapForbiddenError(Exception):
    pass


class BattleMapRevisionConflictError(Exception):
    pass


class BattleMapShrinkConflictError(Exception):
    pass


class BattleMapInvalidError(Exception):
    pass


class BattleMapAssetInvalidError(Exception):
    pass


class BattleMapArchivedError(Exception):
    pass


class BattleMapReferencedError(Exception):
    pass


class MapMonsterPlacementInvalidError(Exception):
    """A placement batch the map rejects (HTTP 409 map_monster_placement_invalid).

    Carries every problem (placement id + code); only ever surfaced to
    owner|dm readers.
    """

    def __init__(self, problems: list[MonsterPlacementProblem]) -> None:
        self.problems = problems
        detail = ", ".join(
            f"{problem.placement_id}:{problem.code}" for problem in problems
        )
        super().__init__(f"monster placements invalid: {detail}")


class MonsterPlacementReferenceNotFoundError(Exception):
    """A referenced template is missing or in another Room (HTTP 404)."""

    pass


class MonsterPlacementSourceError(Exception):
    """The placement source is malformed: not exactly one source, or duplicate
    placement ids in one replace payload (HTTP 422)."""

    pass


__all__ = [
    "MAX_DIMENSION_CELLS",
    "MAX_DRAWING_PAYLOAD_BYTES",
    "BattleMap",
    "BattleMapArchive",
    "BattleMapArchivedError",
    "BattleMapAssetInvalidError",
    "BattleMapAudience",
    "BattleMapCopy",
    "BattleMapCreate",
    "BattleMapDoor",
    "BattleMapDoorInput",
    "BattleMapDoorState",
    "BattleMapDrawing",
    "BattleMapDrawingInput",
    "BattleMapForbiddenError",
    "BattleMapInvalidError",
    "BattleMapMonsterPlacement",
    "BattleMapMonsterPlacementVisibility",
    "BattleMapNotFoundError",
    "BattleMapObjectsReplace",
    "BattleMapPatch",
    "BattleMapReferencedError",
    "BattleMapRevisionConflictError",
    "BattleMapShrinkConflictError",
    "BattleMapSourceKind",
    "BattleMapSummary",
    "BattleMapTerrain",
    "BattleMapTerrainInput",
    "BattleMapTerrainKind",
    "BattleMapWall",
    "BattleMapWallInput",
    "BattleMapWallVisibility",
    "MapMonsterPlacementInvalidError",
    "MonsterPlacementInput",
    "MonsterPlacementProblem",
    "MonsterPlacementReferenceNotFoundError",
    "MonsterPlacementSourceError",
    "MonsterPlacementsReplace",
    "ProjectedBattleMap",
    "ProjectedBattleMapDoor",
    "ProjectedBattleMapWall",
    "TemporaryBattleMapInput",
]
