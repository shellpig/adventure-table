from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import Field

from app.content.registry import ContentRegistry
from app.domain.combat.board import CombatBoardService
from app.domain.combat.lifecycle import CombatNotFoundError, CombatService, CombatStateConflictError
from app.domain.combat.sizes import parse_size, resolve_entry_size
from app.domain.combat.resolution import (
    SizeCategory,
    SpecialAttackKind,
    resolve_grapple_or_shove,
)
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollModifierMode, RollRequestType, RollService
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.domain.rules.abilities import ability_modifier
from app.domain.spatial import (
    BarrierSegment,
    GridCell,
    PathCreature,
    PathValidationRequest,
    footprint_for_size,
    occupied_cells,
    validate_movement_path,
)
from app.persistence.characters import CharacterRepository
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.lifecycle import CombatRepository, StoredCombatEntry, actor_binding
from app.persistence.combat_boards.repository import CombatBoardRepository
from app.persistence.combat.repository import MonsterRepository
from app.persistence.combat.special_attacks import (
    GRAPPLED_REF,
    SpecialAttackNotFoundError,
    SpecialAttackPush,
    SpecialAttackRepository,
    SpecialAttackRollComputation,
    SpecialAttackRollUnit,
    SpecialAttackStateConflictError,
    StoredSpecialAttackAction,
)


ATHLETICS_REF = "srd5.1:skill:athletics"
ACROBATICS_REF = "srd5.1:skill:acrobatics"


class SpecialAttackRequestInput(StrictModel):
    attacker_entry_id: UUID
    target_entry_id: UUID
    kind: SpecialAttackKind
    attacker_modifier_mode: RollModifierMode = RollModifierMode.NORMAL
    defender_modifier_mode: RollModifierMode = RollModifierMode.NORMAL
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class SpecialAttackAdjudicationInput(StrictModel):
    action_id: UUID
    in_reach: bool
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class SpecialAttackView(StrictModel):
    action_id: UUID
    combat_id: UUID
    attacker_entry_id: UUID
    target_entry_id: UUID
    kind: SpecialAttackKind
    status: str
    in_reach: bool | None
    attacker_roll_request_id: UUID | None
    defender_roll_request_id: UUID | None
    attacker_skill: str
    defender_skill: str
    resolution_result: dict[str, Any] | None


def _view(item: StoredSpecialAttackAction) -> SpecialAttackView:
    return SpecialAttackView(
        action_id=item.action_id,
        combat_id=item.combat_id,
        attacker_entry_id=item.attacker_entry_id,
        target_entry_id=item.target_entry_id,
        kind=item.kind,
        status=item.status,
        in_reach=item.in_reach,
        attacker_roll_request_id=item.attacker_roll_request_id,
        defender_roll_request_id=item.defender_roll_request_id,
        attacker_skill=item.attacker_skill,
        defender_skill=item.defender_skill,
        resolution_result=dict(item.resolution_result) if item.resolution_result else None,
    )


class CombatSpecialAttackService:
    """Actor-neutral 2014 Grapple/Shove service on formal opposed checks."""

    def __init__(
        self,
        repository: SpecialAttackRepository,
        core_roll_repository: CombatCoreRollRepository,
        combat_repository: CombatRepository,
        combat_service: CombatService,
        character_repository: CharacterRepository,
        monster_repository: MonsterRepository,
        registry: ContentRegistry,
        roll_service: RollService,
        table_event_service: TableEventService,
        board_repository: CombatBoardRepository | None = None,
        board_service: CombatBoardService | None = None,
    ) -> None:
        self.repository = repository
        self.core_roll_repository = core_roll_repository
        self.combat_repository = combat_repository
        self.combat_service = combat_service
        self.character_repository = character_repository
        self.monster_repository = monster_repository
        self.registry = registry
        self.roll_service = roll_service
        self.table_event_service = table_event_service
        # P5-E: Tactical shove push needs board positions. Falls back to the
        # combat service's board repository when not explicitly wired.
        self.board_repository = board_repository or combat_service.board_repository
        # P5-E E1b: push destination validation reuses the movement path
        # validator against a board projection.
        self.board_service = board_service

    def _active_entry(self, actor: TableActorContext, entry_id: UUID) -> StoredCombatEntry:
        combat = self.combat_repository.get_active(actor.campaign_id)
        if combat is None:
            raise CombatNotFoundError("Campaign has no active Combat")
        entry = self.combat_repository.get_entry(entry_id)
        if entry is None or entry.combat_id != combat.id or entry.status != "active":
            raise CombatNotFoundError("CombatEntry is missing or inactive")
        return entry

    @staticmethod
    def _parse_size(value: object) -> SizeCategory:
        return parse_size(value)

    def _size(self, entry: StoredCombatEntry) -> SizeCategory:
        return resolve_entry_size(
            entry,
            character_repository=self.character_repository,
            monster_repository=self.monster_repository,
            registry=self.registry,
        )

    def _push_destination(
        self,
        *,
        attacker: StoredCombatEntry,
        target: StoredCombatEntry,
    ) -> GridCell | None:
        """Compute the 5-ft shove push destination (P5-E, Tactical only).

        Direction is per-axis sign from the attacker footprint center to the
        target footprint center (diagonal allowed). Returns None when the
        board has no positions for the entries.
        """
        if self.board_repository is None:
            return None
        positions = {
            position.combat_entry_id: position
            for position in self.board_repository.list_positions(attacker.combat_id)
        }
        attacker_pos = positions.get(attacker.id)
        target_pos = positions.get(target.id)
        if attacker_pos is None or target_pos is None:
            return None
        attacker_footprint = footprint_for_size(self._size(attacker))
        target_footprint = footprint_for_size(self._size(target))
        ax = attacker_pos.anchor_x + attacker_footprint.width / 2
        ay = attacker_pos.anchor_y + attacker_footprint.height / 2
        tx = target_pos.anchor_x + target_footprint.width / 2
        ty = target_pos.anchor_y + target_footprint.height / 2
        dx = 1 if tx > ax else (-1 if tx < ax else 0)
        dy = 1 if ty > ay else (-1 if ty < ay else 0)
        return GridCell(target_pos.anchor_x + dx, target_pos.anchor_y + dy)

    def _validate_push_destination(
        self,
        *,
        combat_id: UUID,
        target: StoredCombatEntry,
        destination: GridCell,
        is_dm: bool,
    ) -> bool:
        """Check a shove push destination via the movement path validator.

        Builds a single-step PathValidationRequest against the caller's board
        projection (is_dm=False: caller-visible, hidden creatures/doors
        concealed; is_dm=True: full truth) and runs validate_movement_path.
        This covers blocked terrain, wall/closed-door crossing (including
        diagonal corner cuts), out-of-bounds, and occupied cells without any
        hand-written bounds/occupancy loops.
        Returns False when the destination is not a legal single step.
        """
        if self.board_repository is None or self.board_service is None:
            return False
        board = self.board_repository.get_board(combat_id)
        if board is None:
            return False
        combat = self.combat_repository.get(combat_id)
        if combat is None:
            return False
        position = self.board_repository.get_position(target.id)
        if position is None:
            return False
        view = self.board_service._project_board(combat, board, is_dm=is_dm)
        target_size = self._size(target)
        target_footprint = footprint_for_size(target_size)
        barriers = tuple(
            BarrierSegment(x1=wall.x1, y1=wall.y1, x2=wall.x2, y2=wall.y2)
            for wall in view.walls
        ) + tuple(
            BarrierSegment(x1=door.x1, y1=door.y1, x2=door.x2, y2=door.y2)
            for door in view.doors
            if door.state in ("closed", "locked")
        )
        blocked_cells: set[GridCell] = set()
        for terrain in view.terrain:
            if terrain.terrain_kind == "blocked":
                blocked_cells.add(GridCell(terrain.x, terrain.y))
        creatures: list[PathCreature] = []
        for board_position in view.positions:
            if board_position.entry_id == target.id:
                continue
            other = self.combat_repository.get_entry(board_position.entry_id)
            if other is None or other.status != "active":
                continue
            other_size = resolve_entry_size(
                other,
                character_repository=self.character_repository,
                monster_repository=self.monster_repository,
                registry=self.registry,
            )
            other_footprint = footprint_for_size(other_size)
            creatures.append(PathCreature(
                cells=frozenset(
                    occupied_cells(
                        board_position.anchor_x, board_position.anchor_y,
                        other_footprint,
                    )
                ),
                hostile_to_mover=bool(other.is_hostile) != bool(target.is_hostile),
                size_rank=int(other_size),
            ))
        request = PathValidationRequest(
            start=GridCell(position.anchor_x, position.anchor_y),
            anchors=(destination,),
            footprint=target_footprint,
            mover_size_rank=int(target_size),
            width_cells=view.width_cells,
            height_cells=view.height_cells,
            blocked_cells=frozenset(blocked_cells),
            difficult_cells=frozenset(),
            barriers=barriers,
            creatures=tuple(creatures),
            budget_feet=5,
            diagonal_steps_used=0,
        )
        result = validate_movement_path(request)
        return result.valid

    def _has_free_hand(self, entry: StoredCombatEntry) -> bool:
        if entry.subject_kind == "monster":
            if entry.monster_instance_id is None:
                raise CombatStateConflictError("Monster CombatEntry has no Monster identity")
            monster = self.monster_repository.get_instance(entry.monster_instance_id)
            if monster is None:
                raise CombatNotFoundError("Monster Instance was not found")
            explicit = monster.rules_snapshot.get("free_hands")
            return bool(explicit) if isinstance(explicit, int) else True
        if entry.subject_kind != "character" or entry.character_id is None:
            raise CombatStateConflictError("Special Attack attacker has no Character identity")
        character = self.character_repository.load_character(entry.character_id)
        occupied = 0
        for inventory in character.state.inventory_state:
            if not inventory.equipped:
                continue
            content = self.registry.get_optional(inventory.item_ref)
            if content is None:
                continue
            data = dict(content.data)
            if content.index == "shield":
                occupied += 1
                continue
            if not isinstance(data.get("weapon_range"), str):
                continue
            raw_properties = data.get("properties")
            two_handed = False
            if isinstance(raw_properties, list):
                for raw in raw_properties:
                    if isinstance(raw, dict):
                        candidate = raw.get("index") or raw.get("name")
                    else:
                        candidate = raw
                    if isinstance(candidate, str) and candidate.strip().casefold().replace(" ", "-") == "two-handed":
                        two_handed = True
                        break
            occupied += 2 if two_handed else 1
        return occupied < 2

    def _character_skill_modifier(self, character_id: UUID, skill_ref: str) -> int:
        return self.roll_service.modifier_resolver.modifier_for(
            character_id=character_id,
            request_type=RollRequestType.SKILL,
            ability_ref=None,
            skill_ref=skill_ref,
        )

    @staticmethod
    def _monster_skill_modifier(rules: dict[str, Any], skill_ref: str) -> int:
        skill = skill_ref.rsplit(":", 1)[-1]
        ability = "strength" if skill == "athletics" else "dexterity"
        scores = rules.get("ability_scores", {})
        score = scores.get(ability, 10) if isinstance(scores, dict) else 10
        base = ability_modifier(score if isinstance(score, int) else 10)
        proficiencies = rules.get("proficiencies", [])
        if not isinstance(proficiencies, list):
            return base
        expected = {skill, f"skill-{skill}"}
        for raw in proficiencies:
            if not isinstance(raw, dict):
                continue
            reference = raw.get("proficiency")
            index = None
            if isinstance(reference, dict):
                candidate = reference.get("index") or reference.get("name")
                if isinstance(candidate, str):
                    index = candidate.strip().casefold().replace(" ", "-")
            value = raw.get("value")
            if index in expected and isinstance(value, int):
                return value
        return base

    def _skill_unit(
        self,
        actor: TableActorContext,
        entry: StoredCombatEntry,
        skill_ref: str,
        modifier_mode: RollModifierMode,
        *,
        role: str,
    ) -> SpecialAttackRollUnit:
        if entry.subject_kind == "character":
            if entry.character_id is None:
                raise CombatStateConflictError("Character CombatEntry has no Character identity")
            seat_id = self.combat_repository.controlling_seat_for_character(
                campaign_id=actor.campaign_id,
                session_id=actor.session_id,
                character_id=entry.character_id,
            )
            modifier = self._character_skill_modifier(entry.character_id, skill_ref)
            return SpecialAttackRollUnit(
                role=role,
                target_entry_id=entry.id,
                target_seat_id=seat_id,
                target_character_id=entry.character_id,
                skill_ref=skill_ref,
                modifier=modifier,
                modifier_mode=modifier_mode.value,
            )
        if entry.subject_kind == "monster":
            if entry.monster_instance_id is None:
                raise CombatStateConflictError("Monster CombatEntry has no Monster identity")
            monster = self.monster_repository.get_instance(entry.monster_instance_id)
            if monster is None:
                raise CombatNotFoundError("Monster Instance was not found")
            return SpecialAttackRollUnit(
                role=role,
                target_entry_id=entry.id,
                target_seat_id=None,
                target_character_id=None,
                skill_ref=skill_ref,
                modifier=self._monster_skill_modifier(monster.rules_snapshot, skill_ref),
                modifier_mode=modifier_mode.value,
            )
        raise CombatStateConflictError(f"unsupported CombatEntry kind: {entry.subject_kind}")

    def _is_grappled(self, entry: StoredCombatEntry) -> bool:
        ctx = self.combat_service.condition_context(entry)
        return GRAPPLED_REF in ctx.conditions

    def _best_escape_unit(
        self,
        actor: TableActorContext,
        entry: StoredCombatEntry,
        mode: RollModifierMode,
        *,
        role: str,
    ) -> SpecialAttackRollUnit:
        athletics = self._skill_unit(
            actor,
            entry,
            ATHLETICS_REF,
            mode,
            role=role,
        )
        acrobatics = self._skill_unit(
            actor,
            entry,
            ACROBATICS_REF,
            mode,
            role=role,
        )
        return acrobatics if acrobatics.modifier > athletics.modifier else athletics

    def request_special_attack(
        self,
        actor: TableActorContext,
        request: SpecialAttackRequestInput,
    ) -> SpecialAttackView:
        self.table_event_service.require_actor_current(actor)
        attacker = self._active_entry(actor, request.attacker_entry_id)
        target = self._active_entry(actor, request.target_entry_id)
        if attacker.combat_id != target.combat_id:
            raise CombatStateConflictError("Attacker and target must belong to the same Combat")
        if attacker.id == target.id:
            raise CombatStateConflictError("Special Attack target must be a different CombatEntry")
        subject_seat_id, execution_mode = self.combat_service._authorize_entry(actor, attacker)

        if request.kind is SpecialAttackKind.ESCAPE_GRAPPLE:
            if not self._is_grappled(attacker):
                raise CombatStateConflictError("Combatant is not grappled")
            attacker_unit = self._best_escape_unit(
                actor,
                attacker,
                request.attacker_modifier_mode,
                role="attacker",
            )
            defender_unit = self._skill_unit(
                actor,
                target,
                ATHLETICS_REF,
                request.defender_modifier_mode,
                role="defender",
            )
            try:
                stored, _event = self.repository.request_escape(
                    binding=actor_binding(actor),
                    combat_id=attacker.combat_id,
                    attacker_entry_id=attacker.id,
                    target_entry_id=target.id,
                    subject_seat_id=subject_seat_id,
                    execution_mode=execution_mode,
                    attacker_unit=attacker_unit,
                    defender_unit=defender_unit,
                    idempotency_key=request.idempotency_key,
                )
            except SpecialAttackStateConflictError as exc:
                raise CombatStateConflictError(str(exc)) from exc
            if self.table_event_service.notifier is not None:
                self.table_event_service.notifier.notify(actor.session_id)
            return _view(stored)

        attacker_size = self._size(attacker)
        target_size = self._size(target)
        free_hand = self._has_free_hand(attacker)
        preflight = resolve_grapple_or_shove(
            kind=request.kind,
            attacker_size=attacker_size,
            target_size=target_size,
            attacker_check_total=0,
            target_check_total=0,
            attacker_has_free_hand=free_hand,
            reach_confirmed=None,
        )
        if preflight.status == "invalid":
            raise CombatStateConflictError(preflight.reason or "Special Attack is invalid")
        if preflight.status != "dm_adjudication_required":
            raise CombatStateConflictError("Special Attack preflight did not require geometry adjudication")

        # P5-E: Tactical shove push preflight against caller-visible board.
        # Out of bounds, blocked, wall/door, or occupied → 409, zero side
        # effects, no rolls created.
        combat = self.combat_repository.get_active(actor.campaign_id)
        if (
            request.kind is SpecialAttackKind.SHOVE_PUSH
            and combat is not None
            and combat.mode == "tactical"
        ):
            destination = self._push_destination(attacker=attacker, target=target)
            if destination is None or not self._validate_push_destination(
                combat_id=combat.id,
                target=target,
                destination=destination,
                is_dm=actor.is_current_dm,
            ):
                raise CombatStateConflictError(
                    "Shove push destination is out of bounds, blocked, or occupied"
                )

        attacker_unit = self._skill_unit(
            actor,
            attacker,
            ATHLETICS_REF,
            request.attacker_modifier_mode,
            role="attacker",
        )
        defender_unit = self._best_escape_unit(
            actor,
            target,
            request.defender_modifier_mode,
            role="defender",
        )
        try:
            stored, _event = self.repository.request(
                binding=actor_binding(actor),
                combat_id=attacker.combat_id,
                attacker_entry_id=attacker.id,
                target_entry_id=target.id,
                subject_seat_id=subject_seat_id,
                execution_mode=execution_mode,
                kind=request.kind,
                attacker_size=attacker_size,
                target_size=target_size,
                attacker_has_free_hand=free_hand,
                attacker_unit=attacker_unit,
                defender_unit=defender_unit,
                idempotency_key=request.idempotency_key,
            )
        except SpecialAttackStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return _view(stored)

    def adjudicate_special_attack(
        self,
        actor: TableActorContext,
        request: SpecialAttackAdjudicationInput,
    ) -> SpecialAttackView:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError("Only the current Session DM can adjudicate Quick Combat reach")
        try:
            stored, _event = self.repository.adjudicate_reach(
                binding=actor_binding(actor),
                action_id=request.action_id,
                in_reach=request.in_reach,
                idempotency_key=request.idempotency_key,
            )
        except SpecialAttackStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return _view(stored)

    @staticmethod
    def _authorize_roll(
        actor: TableActorContext,
        target_seat_id: UUID | None,
    ) -> tuple[UUID, str]:
        if target_seat_id is None:
            if not actor.is_current_dm:
                raise TableEventActorUnauthorizedError("Only the current Session DM can roll for Monster combatants")
            return actor.seat_id, "self"
        if target_seat_id in actor.controlled_seat_ids:
            return target_seat_id, "self"
        if actor.is_current_dm:
            return actor.seat_id, "dm_proxy"
        raise TableEventActorUnauthorizedError("Actor cannot complete this Special Attack RollRequest")

    def complete_special_attack_roll(
        self,
        actor: TableActorContext,
        input: FormalRollInput,
    ) -> SpecialAttackView:
        self.table_event_service.require_actor_current(actor)
        action = self.repository.find_by_roll_request(
            session_id=actor.session_id,
            request_id=input.roll_request_id,
        )
        if action is None:
            raise SpecialAttackNotFoundError(str(input.roll_request_id))
        request = self.core_roll_repository.get_request(
            session_id=actor.session_id,
            request_id=input.roll_request_id,
        )
        if request is None or request.request_type != "skill":
            raise SpecialAttackNotFoundError(str(input.roll_request_id))
        acting_seat_id, execution_mode = self._authorize_roll(actor, request.target_seat_id)

        def compute() -> SpecialAttackRollComputation:
            audit = self.roll_service.engine.d20(
                mode=RollModifierMode(request.modifier_mode),
                base_modifier=0,
                flat_adjustment=request.flat_adjustment,
                physical_raw_dice=input.raw_dice if input.source is FormalRollSource.PHYSICAL else None,
            )
            return SpecialAttackRollComputation(
                source=input.source.value,
                formula=audit.formula,
                raw_dice=audit.raw_dice,
                kept_dice=audit.kept_dice,
                base_modifier=audit.base_modifier,
                flat_adjustment=audit.flat_adjustment,
                total=audit.total,
            )

        # P5-E E1b: Tactical shove push. Pre-compute and validate the
        # destination against full truth before the transaction; the
        # repository applies it atomically with the roll resolution only on
        # a successful push. A hidden blocker (validation fails against
        # truth) means push=None: the shove can still succeed but the target
        # does not move, and the event leaks nothing.
        # Forced movement never triggers opportunity attacks and never deals
        # fall/hazard damage (position row is updated directly, not via
        # MovementService.confirm).
        push: SpecialAttackPush | None = None
        if action.kind == SpecialAttackKind.SHOVE_PUSH and self.board_repository is not None:
            combat = self.combat_repository.get(action.combat_id)
            if combat is not None and combat.mode == "tactical":
                attacker = self.combat_repository.get_entry(action.attacker_entry_id)
                target = self.combat_repository.get_entry(action.target_entry_id)
                if attacker is not None and target is not None:
                    destination = self._push_destination(attacker=attacker, target=target)
                    position = self.board_repository.get_position(target.id)
                    if destination is not None and position is not None and self._validate_push_destination(
                        combat_id=combat.id,
                        target=target,
                        destination=destination,
                        is_dm=True,
                    ):
                        footprint = footprint_for_size(self._size(target))
                        push = SpecialAttackPush(
                            target_entry_id=target.id,
                            expected_position_revision=int(position.revision),
                            anchor_x=destination.x,
                            anchor_y=destination.y,
                            footprint_width=footprint.width,
                            footprint_height=footprint.height,
                        )

        try:
            stored, _event = self.repository.complete_roll(
                binding=actor_binding(actor),
                request_id=input.roll_request_id,
                acting_seat_id=acting_seat_id,
                execution_mode=execution_mode,
                result_factory=compute,
                idempotency_key=input.idempotency_key,
                push=push,
            )
        except SpecialAttackStateConflictError as exc:
            raise CombatStateConflictError(str(exc)) from exc
        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)
        return _view(stored)



__all__ = [
    "ACROBATICS_REF",
    "ATHLETICS_REF",
    "CombatSpecialAttackService",
    "SpecialAttackAdjudicationInput",
    "SpecialAttackNotFoundError",
    "SpecialAttackRequestInput",
    "SpecialAttackView",
]
