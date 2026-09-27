from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Iterable, Literal
from uuid import UUID

from pydantic import Field, model_validator

from app.content.registry import ContentRegistry
from app.domain.battle_maps.schemas import BattleMapNotFoundError
from app.domain.combat.projection import CombatantAudience, project_combatant
from app.domain.combat.speeds import resolve_entry_walk_speed
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import TableActorContext, TableEventActorUnauthorizedError, TableEventService
from app.persistence.characters import CharacterRepository
from app.persistence.combat.combatants import (
    character_to_combatant,
    monster_instance_to_combatant,
)
from app.persistence.combat.core_rolls import _condition_ref
from app.persistence.combat.lifecycle import (
    ActiveCombatExistsPersistenceError, CombatNotFoundPersistenceError,
    CombatRepository, CombatStateConflictPersistenceError,
    NewCombatEntry, StoredCombat, StoredCombatEntry, actor_binding,
)
from app.persistence.battle_maps.repository import BattleMapRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat_boards.repository import CombatBoardRepository, StoredBoardDoor, StoredCombatBoard


class CombatLifecycleError(RuntimeError): pass
class CombatNotFoundError(LookupError): pass
class ActiveCombatExistsError(CombatLifecycleError): pass
class CombatStateConflictError(CombatLifecycleError): pass
class CombatPlacementIncompleteError(CombatLifecycleError): pass


class CombatActionKind(StrEnum):
    DASH = "dash"
    DISENGAGE = "disengage"
    DODGE = "dodge"
    SEARCH = "search"
    READY = "ready"
    FREEFORM = "freeform"
    ATTACK_BUDGET = "attack_budget"


class CombatEconomyCost(StrEnum):
    ACTION = "action"
    BONUS_ACTION = "bonus_action"
    REACTION = "reaction"
    NONE = "none"


class StartCombatInput(StrictModel):
    include_active_party: bool = True
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class StartTacticalCombatInput(StrictModel):
    """P5-A tactical start: freeze a battle map (or a blank board) as the Combat board."""

    battle_map_id: UUID | None = None
    blank_width_cells: int | None = Field(default=None, ge=1, le=200)
    blank_height_cells: int | None = Field(default=None, ge=1, le=200)
    include_active_party: bool = True
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def _require_map_or_blank_dimensions(self) -> StartTacticalCombatInput:
        if self.battle_map_id is None and (
            self.blank_width_cells is None or self.blank_height_cells is None
        ):
            raise ValueError(
                "blank_width_cells and blank_height_cells are required when battle_map_id is omitted"
            )
        return self


class AddCharacterInput(StrictModel):
    character_id: UUID
    surprised: bool = False
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class AddMonsterInput(StrictModel):
    monster_instance_id: UUID
    surprised: bool = False
    initiative_group_key: str | None = Field(default=None, max_length=120)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class ResolveInitiativeOrderInput(StrictModel):
    ordered_entry_ids: tuple[UUID, ...] = Field(min_length=1)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)
    @model_validator(mode="after")
    def unique_entries(self):
        if len(self.ordered_entry_ids) != len(set(self.ordered_entry_ids)):
            raise ValueError("ordered_entry_ids must be unique")
        return self


class CombatActionInput(StrictModel):
    entry_id: UUID
    action_kind: CombatActionKind
    economy_cost: CombatEconomyCost = CombatEconomyCost.ACTION
    payload: dict[str, Any] = Field(default_factory=dict)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def structured_actions_require_action_economy(self):
        if (
            self.action_kind is not CombatActionKind.FREEFORM
            and self.economy_cost is not CombatEconomyCost.ACTION
        ):
            raise ValueError(
                f"{self.action_kind.value} requires Action economy; "
                "only freeform actions may choose another economy cost"
            )
        return self


class ReactionWindowInput(StrictModel):
    entry_id: UUID
    open: bool
    reason: str | None = Field(default=None, max_length=240)
    source_entry_id: UUID | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


MonsterOutcome = Literal["dead", "unconscious", "surrendered", "fled", "other"]


class MonsterOutcomeChoice(StrictModel):
    """DM ruling on a Monster entry; the REST body (entry id travels in the path)."""
    outcome: MonsterOutcome
    note: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def note_required_when_other(self):
        if self.outcome == "other" and (self.note is None or not self.note.strip()):
            raise ValueError("note is required when outcome is 'other'")
        return self


class MonsterOutcomeInput(MonsterOutcomeChoice):
    entry_id: UUID


class CombatEntryView(StrictModel):
    id: UUID
    subject_kind: str
    character_id: UUID | None
    monster_instance_id: UUID | None
    display_name: str
    status: str
    initiative_group_key: str | None
    initiative_roll_request_id: UUID | None
    initiative_roll_result_id: UUID | None
    initiative_total: int | None
    turn_order: int | None
    surprised: bool
    action_available: bool
    bonus_action_available: bool
    reaction_available: bool
    attacks_allowed: int
    attacks_used: int
    ready_state: dict[str, Any]
    pending_reaction_state: dict[str, Any]
    dodging: bool = False
    disengaged: bool = False


class CombatView(StrictModel):
    id: UUID
    campaign_id: UUID
    mode: str
    status: str
    round_number: int | None
    current_turn_entry_id: UUID | None
    revision: int
    entries: tuple[CombatEntryView, ...]
    warnings: tuple[str, ...] = ()


class CombatantDetailView(StrictModel):
    entry_id: UUID
    subject_kind: str
    is_hostile: bool
    projection: dict[str, Any]


class CombatDetailView(CombatView):
    combatants: tuple[CombatantDetailView, ...] = ()


class CombatActionView(StrictModel):
    id: UUID
    combat_id: UUID
    entry_id: UUID
    session_id: UUID
    acting_seat_id: UUID
    subject_seat_id: UUID | None
    execution_mode: str
    action_kind: str
    economy_cost: str
    payload: dict[str, Any]


def _extra_attack_budget(character) -> int:
    progression = Counter(str(ref).rsplit(":", 1)[-1].replace("_", "-").casefold() for ref in character.build.class_progression)
    fighter = progression.get("fighter", 0)
    if fighter >= 20: return 4
    if fighter >= 11: return 3
    if fighter >= 5: return 2
    for class_name in ("barbarian", "monk", "paladin", "ranger"):
        if progression.get(class_name, 0) >= 5: return 2
    if any("extra-attack" in str(ref).replace("_", "-").casefold() for ref in character.build.feature_refs):
        return 2
    return 1


@dataclass(frozen=True)
class EntryConditionContext:
    conditions: tuple[str, ...]
    exhaustion_level: int
    dodging: bool = False


class CombatService:
    """Actor-neutral P4-B application service shared by Human and AI adapters."""
    def __init__(self, repository: CombatRepository, table_event_service: TableEventService,
                 character_repository: CharacterRepository, monster_repository: MonsterRepository,
                 registry: ContentRegistry,
                 battle_map_repository: BattleMapRepository | None = None,
                 board_repository: CombatBoardRepository | None = None) -> None:
        self.repository = repository
        self.table_event_service = table_event_service
        self.character_repository = character_repository
        self.monster_repository = monster_repository
        self.registry = registry
        self.battle_map_repository = battle_map_repository
        self.board_repository = board_repository

    def condition_context(self, entry: StoredCombatEntry) -> EntryConditionContext:
        if entry.subject_kind == "character":
            if entry.character_id is None:
                raise CombatStateConflictError("Character CombatEntry has no Character identity")
            character = self.character_repository.load_character(entry.character_id)
            conditions = tuple(str(item.condition_ref) for item in character.state.conditions)
            return EntryConditionContext(
                conditions=conditions,
                exhaustion_level=int(character.state.exhaustion_level),
                dodging=entry.dodging,
            )
        if entry.subject_kind == "monster":
            if entry.monster_instance_id is None:
                raise CombatStateConflictError("Monster CombatEntry has no Monster identity")
            monster = self.monster_repository.get_instance(entry.monster_instance_id)
            if monster is None:
                raise CombatNotFoundError("Monster Instance was not found")
            conditions = tuple(
                ref
                for item in monster.conditions
                if (ref := _condition_ref(item)) is not None
            )
            return EntryConditionContext(
                conditions=conditions,
                exhaustion_level=0,
                dodging=entry.dodging,
            )
        raise CombatStateConflictError(f"unsupported CombatEntry kind: {entry.subject_kind}")

    def _current(self, actor: TableActorContext) -> None:
        self.table_event_service.require_actor_current(actor)

    def _require_dm(self, actor: TableActorContext) -> None:
        self._current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError("Only the current Session DM can perform this Combat operation")

    def _notify(self, actor: TableActorContext) -> None:
        # Wake long-poll event waiters (Player pages / AI wait_for_event) after a Combat mutation.
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)

    @staticmethod
    def _entry_view(entry: StoredCombatEntry) -> CombatEntryView:
        return CombatEntryView(
            id=entry.id, subject_kind=entry.subject_kind, character_id=entry.character_id,
            monster_instance_id=entry.monster_instance_id, display_name=entry.display_name,
            status=entry.status, initiative_group_key=entry.initiative_group_key,
            initiative_roll_request_id=entry.initiative_roll_request_id,
            initiative_roll_result_id=entry.initiative_roll_result_id,
            initiative_total=entry.initiative_total, turn_order=entry.turn_order,
            surprised=entry.surprised, action_available=entry.action_available,
            bonus_action_available=entry.bonus_action_available, reaction_available=entry.reaction_available,
            attacks_allowed=entry.attacks_allowed, attacks_used=entry.attacks_used,
            ready_state=dict(entry.ready_state), pending_reaction_state=dict(entry.pending_reaction_state),
            dodging=entry.dodging, disengaged=entry.disengaged,
        )

    def _hidden_entry_ids(self, entries: tuple[StoredCombatEntry, ...]) -> frozenset[UUID]:
        """Entry ids of hidden Monster combatants — never shown to Players (P5-A B6)."""
        hidden: set[UUID] = set()
        for entry in entries:
            if entry.subject_kind != "monster" or entry.monster_instance_id is None:
                continue
            instance = self.monster_repository.get_instance(entry.monster_instance_id)
            if instance is not None and instance.visibility == "hidden":
                hidden.add(entry.id)
        return frozenset(hidden)

    def require_tactical_placements(self, combat_id: UUID, entry_ids: Iterable[UUID]) -> None:
        """Initiative gate (P5-A): every targeted Tactical entry must have a board position."""
        if self.board_repository is None:
            return
        missing = [entry_id for entry_id in entry_ids if self.board_repository.get_position(entry_id) is None]
        if missing:
            raise CombatPlacementIncompleteError(
                f"{len(missing)} combatant(s) have no board position; "
                "place every combatant before initiative proceeds"
            )

    def _view(self, combat: StoredCombat, actor: TableActorContext) -> CombatView:
        stored_entries = self.repository.list_entries(combat.id)
        hidden_ids = frozenset() if actor.is_current_dm else self._hidden_entry_ids(tuple(stored_entries))
        current_turn_entry_id = combat.current_turn_entry_id
        if current_turn_entry_id is not None and current_turn_entry_id in hidden_ids:
            current_turn_entry_id = None
        warnings: tuple[str, ...] = ()
        if (
            combat.status in {"initiative_pending", "running"}
            and not self.repository.has_active_hostile(combat.id)
        ):
            # Warning only: P4-B never auto-ends a Combat when hostiles disappear.
            warnings = ("no_hostile_combatants",)
        return CombatView(
            id=combat.id, campaign_id=combat.campaign_id, mode=combat.mode, status=combat.status,
            round_number=combat.round_number, current_turn_entry_id=current_turn_entry_id,
            revision=combat.revision,
            entries=tuple(
                self._entry_view(entry) for entry in stored_entries if entry.id not in hidden_ids
            ),
            warnings=warnings,
        )

    def get_active_combat(self, actor: TableActorContext) -> CombatView | None:
        self._current(actor)
        combat = self.repository.get_active(actor.campaign_id)
        return self._view(combat, actor) if combat is not None else None

    def get_active_combat_detail(self, actor: TableActorContext) -> CombatDetailView | None:
        self._current(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None:
            return None
        base_view = self._view(combat, actor)
        audience: CombatantAudience = "dm" if actor.is_current_dm else "player"
        stored_entries = self.repository.list_entries(combat.id)
        combatant_views: list[CombatantDetailView] = []
        for entry in stored_entries:
            enemy = bool(entry.is_hostile)
            if entry.subject_kind == "character":
                if entry.character_id is None:
                    continue
                character = self.character_repository.load_character(entry.character_id)
                combatant_state = character_to_combatant(character, entry=entry, registry=self.registry)
            elif entry.subject_kind == "monster":
                if entry.monster_instance_id is None:
                    continue
                instance = self.monster_repository.get_instance(entry.monster_instance_id)
                if instance is None:
                    continue
                combatant_state = monster_instance_to_combatant(instance, entry=entry)
            else:
                continue

            projected = project_combatant(combatant_state, audience=audience, enemy=enemy)
            if projected is None:
                # None-projected hidden enemies are omitted entirely from the tuple.
                continue

            combatant_views.append(
                CombatantDetailView(
                    entry_id=entry.id,
                    subject_kind=entry.subject_kind,
                    is_hostile=enemy,
                    projection=projected,
                )
            )

        return CombatDetailView(
            id=base_view.id,
            campaign_id=base_view.campaign_id,
            mode=base_view.mode,
            status=base_view.status,
            round_number=base_view.round_number,
            current_turn_entry_id=base_view.current_turn_entry_id,
            revision=base_view.revision,
            entries=base_view.entries,
            warnings=base_view.warnings,
            combatants=tuple(combatant_views),
        )

    def start_quick_combat(self, actor: TableActorContext, request: StartCombatInput) -> CombatView:
        self._require_dm(actor)
        if self.repository.get_active(actor.campaign_id) is not None:
            raise ActiveCombatExistsError("Campaign already has an active Combat")
        entries: list[NewCombatEntry] = []
        if request.include_active_party:
            for subject in self.repository.session_characters(campaign_id=actor.campaign_id, session_id=actor.session_id):
                character = self.character_repository.load_character(subject.character_id)
                entries.append(NewCombatEntry(
                    subject_kind="character", character_id=subject.character_id,
                    display_name=subject.character_name, attacks_allowed=_extra_attack_budget(character),
                ))
        try:
            combat, _entries, _event = self.repository.create_quick_combat(
                binding=actor_binding(actor), entries=tuple(entries), idempotency_key=request.idempotency_key
            )
        except ActiveCombatExistsPersistenceError as exc:
            raise ActiveCombatExistsError("Campaign already has an active Combat") from exc
        self._notify(actor)
        return self._view(combat, actor)

    def add_character(self, actor: TableActorContext, request: AddCharacterInput) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        if self.repository.controlling_seat_for_character(
            campaign_id=actor.campaign_id, session_id=actor.session_id, character_id=request.character_id
        ) is None:
            raise CombatStateConflictError("Character must be an active participant in the current Session before mid-Combat entry")
        character = self.character_repository.load_character(request.character_id)
        try:
            self.repository.add_entry(
                binding=actor_binding(actor), combat_id=combat.id,
                entry=NewCombatEntry(subject_kind="character", character_id=request.character_id,
                    display_name=character.name, attacks_allowed=_extra_attack_budget(character), surprised=request.surprised),
                idempotency_key=request.idempotency_key,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        self._notify(actor)
        return self._view(self.repository.get(combat.id) or combat, actor)

    def start_tactical_combat(self, actor: TableActorContext, request: StartTacticalCombatInput) -> CombatView:
        """P5-A tactical start: create the Combat, freeze the board, emit combat.started.

        The board freezes the battle map baseline (walls/doors/terrain/drawings) and
        runtime door states at the source map revision, or a blank board when no
        battle map is given. Map Definition is never mutated.
        """
        self._require_dm(actor)
        if self.battle_map_repository is None or self.board_repository is None:
            raise CombatStateConflictError("Tactical Combat is not available")
        # With an idempotency key the persistence layer resolves retries against
        # the stored combat.started event; without one, fail fast here.
        if request.idempotency_key is None and self.repository.get_active(actor.campaign_id) is not None:
            raise ActiveCombatExistsError("Campaign already has an active Combat")
        entries: list[NewCombatEntry] = []
        if request.include_active_party:
            for subject in self.repository.session_characters(campaign_id=actor.campaign_id, session_id=actor.session_id):
                character = self.character_repository.load_character(subject.character_id)
                entries.append(NewCombatEntry(
                    subject_kind="character", character_id=subject.character_id,
                    display_name=subject.character_name, attacks_allowed=_extra_attack_budget(character),
                ))
        board, doors, battle_map_id = self._freeze_board(actor, request)
        try:
            combat, _entries, _event = self.repository.create_tactical_combat(
                binding=actor_binding(actor), entries=tuple(entries), board=board, doors=doors,
                battle_map_id=battle_map_id, idempotency_key=request.idempotency_key,
            )
        except ActiveCombatExistsPersistenceError as exc:
            raise ActiveCombatExistsError("Campaign already has an active Combat") from exc
        self._notify(actor)
        return self._view(combat, actor)

    def _freeze_board(
        self, actor: TableActorContext, request: StartTacticalCombatInput
    ) -> tuple[StoredCombatBoard, tuple[StoredBoardDoor, ...], UUID | None]:
        from datetime import datetime, timezone
        from uuid import uuid4

        assert self.battle_map_repository is not None
        now = datetime.now(timezone.utc)
        placeholder_combat_id = uuid4()
        if request.battle_map_id is not None:
            stored_map = self.battle_map_repository.get_map(actor.room_id, request.battle_map_id)
            if stored_map is None:
                raise BattleMapNotFoundError(f"BattleMap {request.battle_map_id} not found")
            objects = self.battle_map_repository.get_objects(stored_map.id)
            baseline = {
                "walls": [
                    {"id": str(wall.id), "x1": wall.x1, "y1": wall.y1, "x2": wall.x2, "y2": wall.y2,
                     "visibility": wall.visibility}
                    for wall in objects.walls
                ],
                "doors": [
                    {"id": str(door.id), "x1": door.x1, "y1": door.y1, "x2": door.x2, "y2": door.y2,
                     "state": door.default_state, "visibility": door.visibility}
                    for door in objects.doors
                ],
                "terrain": [
                    {"x": terrain.x, "y": terrain.y, "terrain_kind": terrain.terrain_kind}
                    for terrain in objects.terrain
                ],
                "drawings": [
                    {"id": str(drawing.id), "payload": drawing.payload}
                    for drawing in objects.drawings
                ],
            }
            doors = tuple(
                StoredBoardDoor(
                    combat_id=placeholder_combat_id, door_id=door.id,
                    state=door.default_state, revealed=door.visibility == "public",
                    created_at=now,
                )
                for door in objects.doors
            )
            board = StoredCombatBoard(
                combat_id=placeholder_combat_id,
                source_battle_map_id=stored_map.id,
                source_battle_map_revision=stored_map.revision,
                width_cells=stored_map.width_cells, height_cells=stored_map.height_cells,
                grid_pixel_size=stored_map.grid_pixel_size,
                grid_offset_x=stored_map.grid_offset_x, grid_offset_y=stored_map.grid_offset_y,
                image_asset_id=stored_map.image_asset_id,
                baseline=baseline, runtime_revision=1, created_at=now,
            )
            return board, doors, stored_map.id
        board = StoredCombatBoard(
            combat_id=placeholder_combat_id,
            source_battle_map_id=None, source_battle_map_revision=None,
            width_cells=int(request.blank_width_cells or 0),
            height_cells=int(request.blank_height_cells or 0),
            grid_pixel_size=None, grid_offset_x=None, grid_offset_y=None,
            image_asset_id=None,
            baseline={"walls": [], "doors": [], "terrain": [], "drawings": []},
            runtime_revision=1, created_at=now,
        )
        return board, (), None
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        if self.repository.controlling_seat_for_character(
            campaign_id=actor.campaign_id, session_id=actor.session_id, character_id=request.character_id
        ) is None:
            raise CombatStateConflictError("Character must be an active participant in the current Session before mid-Combat entry")
        character = self.character_repository.load_character(request.character_id)
        try:
            self.repository.add_entry(
                binding=actor_binding(actor), combat_id=combat.id,
                entry=NewCombatEntry(subject_kind="character", character_id=request.character_id,
                    display_name=character.name, attacks_allowed=_extra_attack_budget(character), surprised=request.surprised),
                idempotency_key=request.idempotency_key,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        self._notify(actor)
        return self._view(self.repository.get(combat.id) or combat, actor)

    def add_monster(self, actor: TableActorContext, request: AddMonsterInput) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        monster = self.monster_repository.get_instance(request.monster_instance_id)
        if monster is None or monster.campaign_id != actor.campaign_id:
            raise CombatNotFoundError("Monster Instance was not found in this Campaign")
        try:
            self.repository.add_entry(
                binding=actor_binding(actor), combat_id=combat.id,
                entry=NewCombatEntry(subject_kind="monster", monster_instance_id=monster.id,
                    display_name=monster.name, surprised=request.surprised, initiative_group_key=request.initiative_group_key),
                idempotency_key=request.idempotency_key,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        self._notify(actor)
        return self._view(self.repository.get(combat.id) or combat, actor)

    def resolve_initiative_order(self, actor: TableActorContext, request: ResolveInitiativeOrderInput) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        if combat.mode == "tactical":
            # Initiative gate (P5-A): a Tactical Combat may not go running while
            # any active combatant is still unplaced.
            self.require_tactical_placements(
                combat.id,
                tuple(entry.id for entry in self.repository.list_entries(combat.id) if entry.status == "active"),
            )
        try:
            stored, _event = self.repository.resolve_initiative_order(
                binding=actor_binding(actor), combat_id=combat.id,
                ordered_entry_ids=request.ordered_entry_ids, idempotency_key=request.idempotency_key,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        self._notify(actor)
        return self._view(stored, actor)

    def advance_turn(self, actor: TableActorContext, *, idempotency_key: str | None = None) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        try:
            stored, _event = self.repository.advance_turn(
                binding=actor_binding(actor), combat_id=combat.id, idempotency_key=idempotency_key
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        self._notify(actor)
        return self._view(stored, actor)

    def _authorize_entry(self, actor: TableActorContext, entry: StoredCombatEntry) -> tuple[UUID | None, str]:
        if entry.subject_kind == "monster":
            if not actor.is_current_dm:
                raise TableEventActorUnauthorizedError("Only the current Session DM controls Monster combatants")
            return None, "self"
        if entry.character_id is None:
            raise CombatStateConflictError("Character Combat entry has no Character identity")
        subject_seat_id = self.repository.controlling_seat_for_character(
            campaign_id=actor.campaign_id, session_id=actor.session_id, character_id=entry.character_id
        )
        if subject_seat_id is None:
            if actor.is_current_dm:
                # CombatEntry identity is the Character, not a historical Session Seat.
                # When that Character is absent in a later Session the current DM may
                # explicitly proxy it; the action remains audited as dm_proxy with the
                # durable CombatEntry/Character as subject and no fabricated Seat.
                return None, "dm_proxy"
            raise TableEventActorUnauthorizedError("Character Combat entry is not controlled in this Session")
        if subject_seat_id in actor.controlled_seat_ids: return subject_seat_id, "self"
        if actor.is_current_dm: return subject_seat_id, "dm_proxy"
        raise TableEventActorUnauthorizedError("Actor does not control this Character Combat entry")

    def use_action(self, actor: TableActorContext, request: CombatActionInput) -> CombatActionView:
        self._current(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        entry = self.repository.get_entry(request.entry_id)
        if entry is None or entry.combat_id != combat.id: raise CombatNotFoundError("Combat entry was not found")
        subject_seat_id, execution_mode = self._authorize_entry(actor, entry)
        dash_speed_feet: int | None = None
        if request.action_kind is CombatActionKind.DASH and combat.mode == "tactical":
            # P5-B: Dash grants extra movement equal to the entry's current
            # walk speed; the persistence layer adds it to the turn budget in
            # the same transaction as the action economy update.
            condition = self.condition_context(entry)
            dash_speed_feet = resolve_entry_walk_speed(
                entry,
                character_repository=self.character_repository,
                monster_repository=self.monster_repository,
                conditions=condition.conditions,
                exhaustion_level=condition.exhaustion_level,
            )
        try:
            stored, _event = self.repository.consume_action(
                binding=actor_binding(actor), combat_id=combat.id, entry_id=entry.id,
                subject_seat_id=subject_seat_id, execution_mode=execution_mode,
                action_kind=request.action_kind.value, economy_cost=request.economy_cost.value,
                payload=dict(request.payload), idempotency_key=request.idempotency_key,
                attack_use=request.action_kind is CombatActionKind.ATTACK_BUDGET,
                dash_speed_feet=dash_speed_feet,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        self._notify(actor)
        return CombatActionView(
            id=stored.id, combat_id=stored.combat_id, entry_id=stored.entry_id,
            session_id=stored.session_id, acting_seat_id=stored.acting_seat_id,
            subject_seat_id=stored.subject_seat_id, execution_mode=stored.execution_mode,
            action_kind=stored.action_kind, economy_cost=stored.economy_cost, payload=dict(stored.payload),
        )

    def set_reaction_window(self, actor: TableActorContext, request: ReactionWindowInput) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        state: dict[str, Any] = {"open": request.open}
        if request.reason: state["reason"] = request.reason
        if request.source_entry_id: state["source_entry_id"] = str(request.source_entry_id)
        self.repository.set_reaction_window(
            binding=actor_binding(actor), combat_id=combat.id, entry_id=request.entry_id,
            state=state if request.open else {}, idempotency_key=request.idempotency_key,
        )
        self._notify(actor)
        return self._view(self.repository.get(combat.id) or combat, actor)

    def withdraw_entry(self, actor: TableActorContext, entry_id: UUID, *, idempotency_key: str | None = None) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        try:
            self.repository.withdraw_entry(
                binding=actor_binding(actor), combat_id=combat.id, entry_id=entry_id, idempotency_key=idempotency_key
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        self._notify(actor)
        return self._view(self.repository.get(combat.id) or combat, actor)

    def remove_entry(self, actor: TableActorContext, entry_id: UUID, *, idempotency_key: str | None = None) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        try:
            self.repository.remove_entry(
                binding=actor_binding(actor), combat_id=combat.id, entry_id=entry_id, idempotency_key=idempotency_key
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        self._notify(actor)
        return self._view(self.repository.get(combat.id) or combat, actor)

    def set_monster_outcome(self, actor: TableActorContext, request: MonsterOutcomeInput) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        try:
            self.repository.set_monster_outcome(
                binding=actor_binding(actor), combat_id=combat.id, entry_id=request.entry_id,
                outcome=request.outcome, note=request.note, idempotency_key=request.idempotency_key,
            )
        except CombatStateConflictPersistenceError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        except CombatNotFoundPersistenceError as exc:
            raise CombatNotFoundError(str(exc)) from exc
        self._notify(actor)
        return self._view(self.repository.get(combat.id) or combat, actor)

    def end_combat(self, actor: TableActorContext, *, idempotency_key: str | None = None) -> CombatView:
        self._require_dm(actor)
        combat = self.repository.get_active(actor.campaign_id)
        if combat is None: raise CombatNotFoundError("Campaign has no active Combat")
        stored, _event = self.repository.end_combat(
            binding=actor_binding(actor), combat_id=combat.id, idempotency_key=idempotency_key
        )
        self._notify(actor)
        return self._view(stored, actor)


__all__ = [
    "ActiveCombatExistsError", "AddCharacterInput", "AddMonsterInput", "CombatActionInput", "CombatActionKind",
    "CombatActionView", "CombatDetailView", "CombatantDetailView", "CombatEconomyCost", "CombatEntryView",
    "CombatLifecycleError", "CombatNotFoundError", "CombatPlacementIncompleteError", "CombatService",
    "CombatStateConflictError", "CombatView",
    "EntryConditionContext", "MonsterOutcome", "MonsterOutcomeChoice", "MonsterOutcomeInput",
    "ReactionWindowInput", "ResolveInitiativeOrderInput", "StartCombatInput", "StartTacticalCombatInput",
    "_extra_attack_budget",
]
