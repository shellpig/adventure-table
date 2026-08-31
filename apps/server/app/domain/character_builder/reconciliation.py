from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from app.content.registry import ContentRegistry
from app.domain.character.schemas import (
    CharacterBuild,
    CharacterState,
    ResourceCounter,
)
from app.domain.character.validation import (
    CharacterValidationError,
    derive_hit_dice_totals,
    validate_state_against_build,
)
from app.domain.character_builder.schemas import (
    BuilderIssue,
    BuilderIssueSeverity,
)
from app.domain.rules.feature_resources import feature_resource_capacities
from app.domain.rules.hit_points import calculate_max_hp
from app.domain.rules.spellcasting import initial_spell_resource_state


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class StateReconciliationChange(StrictModel):
    path: str = Field(min_length=1, max_length=320)
    kind: str = Field(min_length=1, max_length=80)
    before: str
    after: str
    message: str = Field(min_length=1, max_length=1000)


class StateReconciliationPreview(StrictModel):
    proposed_state: CharacterState
    changes: tuple[StateReconciliationChange, ...] = ()
    blocking_issues: tuple[BuilderIssue, ...] = ()
    warnings: tuple[BuilderIssue, ...] = ()
    can_apply: bool


def _warning(code: str, path: str, message: str) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.WARNING,
        path=path,
        message=message,
    )


def _blocking(code: str, path: str, message: str) -> BuilderIssue:
    return BuilderIssue(
        code=code,
        severity=BuilderIssueSeverity.BLOCKING_ERROR,
        path=path,
        message=message,
    )


def _reconcile_counter(
    *,
    path: str,
    old: ResourceCounter | None,
    new_capacity: int,
    warnings: list[BuilderIssue],
    changes: list[StateReconciliationChange],
) -> ResourceCounter:
    old_used = old.used if old is not None else 0
    old_remaining = old.remaining if old is not None else 0
    old_capacity = old_used + old_remaining
    new_used = min(old_used, new_capacity)
    new_remaining = new_capacity - new_used
    if old_used > new_capacity:
        warnings.append(
            _warning(
                "resource_usage_clamped",
                path,
                (
                    f"Resource usage ({old_used}) exceeds the new capacity "
                    f"({new_capacity}); used is clamped to the new capacity."
                ),
            )
        )
    if old_capacity != new_capacity or old_used != new_used:
        changes.append(
            StateReconciliationChange(
                path=path,
                kind="resource_capacity",
                before=f"used={old_used}, remaining={old_remaining}, capacity={old_capacity}",
                after=f"used={new_used}, remaining={new_remaining}, capacity={new_capacity}",
                message="Preserve prior usage while reconciling to the new Build capacity.",
            )
        )
    return ResourceCounter(used=new_used, remaining=new_remaining)


def reconcile_character_state(
    old_build: CharacterBuild,
    old_state: CharacterState,
    new_build: CharacterBuild,
    registry: ContentRegistry,
) -> StateReconciliationPreview:
    """Reconcile mutable Current State when an immutable Build version changes.

    Level Up is deliberately not a rest. Damage, spent resources, spent hit dice,
    inventory, conditions and temporary HP survive unless a Build invariant forces
    a bounded adjustment. Prepared spells are never silently removed: an invalid
    prepared selection blocks the version change instead.
    """

    warnings: list[BuilderIssue] = []
    blocking: list[BuilderIssue] = []
    changes: list[StateReconciliationChange] = []

    old_max_hp = calculate_max_hp(old_build)
    new_max_hp = calculate_max_hp(new_build)
    old_damage = max(0, old_max_hp - old_state.current_hp)
    unclamped_hp = new_max_hp - old_damage
    new_current_hp = max(0, min(new_max_hp, unclamped_hp))
    if unclamped_hp < 0:
        warnings.append(
            _warning(
                "hp_damage_delta_clamped",
                "state.current_hp",
                (
                    f"Preserved damage ({old_damage}) exceeds the new max HP "
                    f"({new_max_hp}); current HP is clamped to 0."
                ),
            )
        )
    if new_current_hp != old_state.current_hp or old_max_hp != new_max_hp:
        changes.append(
            StateReconciliationChange(
                path="state.current_hp",
                kind="hp_damage_delta",
                before=f"{old_state.current_hp}/{old_max_hp}",
                after=f"{new_current_hp}/{new_max_hp}",
                message=f"Preserved {old_damage} points of existing damage.",
            )
        )

    new_slot_seed, new_spell_resource_seed = initial_spell_resource_state(new_build)
    _old_slot_seed, old_spell_resource_seed = initial_spell_resource_state(old_build)

    new_spell_slots: dict[int, ResourceCounter] = {}
    for level, seed in new_slot_seed.items():
        old_counter = old_state.spell_slots.get(level)
        new_spell_slots[level] = _reconcile_counter(
            path=f"state.spell_slots.{level}",
            old=old_counter,
            new_capacity=seed.remaining,
            warnings=warnings,
            changes=changes,
        )
    removed_slot_levels = set(old_state.spell_slots) - set(new_slot_seed)
    for level in sorted(removed_slot_levels):
        old_counter = old_state.spell_slots[level]
        if old_counter.used or old_counter.remaining:
            warnings.append(
                _warning(
                    "spell_slot_pool_removed",
                    f"state.spell_slots.{level}",
                    f"Spell-slot level {level} no longer exists in the new Build and is removed.",
                )
            )
            changes.append(
                StateReconciliationChange(
                    path=f"state.spell_slots.{level}",
                    kind="resource_removed",
                    before=f"used={old_counter.used}, remaining={old_counter.remaining}",
                    after="removed",
                    message="The new Build no longer has this spell-slot capacity.",
                )
            )

    old_feature_capacities = feature_resource_capacities(old_build, registry)
    new_feature_capacities = feature_resource_capacities(new_build, registry)
    managed_resource_keys = set(old_spell_resource_seed) | set(old_feature_capacities)
    new_resources = {
        key: counter
        for key, counter in old_state.resources.items()
        if key not in managed_resource_keys
    }
    for key, seed in new_spell_resource_seed.items():
        new_resources[key] = _reconcile_counter(
            path=f"state.resources.{key}",
            old=old_state.resources.get(key),
            new_capacity=seed.remaining,
            warnings=warnings,
            changes=changes,
        )
    for key, capacity in new_feature_capacities.items():
        new_resources[key] = _reconcile_counter(
            path=f"state.resources.{key}",
            old=old_state.resources.get(key),
            new_capacity=capacity,
            warnings=warnings,
            changes=changes,
        )

    removed_managed_keys = managed_resource_keys - (
        set(new_spell_resource_seed) | set(new_feature_capacities)
    )
    for key in sorted(removed_managed_keys):
        old_counter = old_state.resources.get(key)
        if old_counter is None:
            continue
        warnings.append(
            _warning(
                "spell_resource_pool_removed",
                f"state.resources.{key}",
                f"Build-derived resource pool {key} no longer exists and is removed.",
            )
        )
        changes.append(
            StateReconciliationChange(
                path=f"state.resources.{key}",
                kind="resource_removed",
                before=f"used={old_counter.used}, remaining={old_counter.remaining}",
                after="removed",
                message="The new Build no longer grants this resource pool.",
            )
        )

    old_hit_dice_totals = derive_hit_dice_totals(old_build, registry)
    new_hit_dice_totals = derive_hit_dice_totals(new_build, registry)
    new_hit_dice_state: dict[str, int] = {}
    for die, new_total in new_hit_dice_totals.items():
        old_total = old_hit_dice_totals.get(die, 0)
        old_available = old_state.hit_dice_state.get(die, 0)
        old_spent = max(0, old_total - old_available)
        new_available = max(0, min(new_total, new_total - old_spent))
        new_hit_dice_state[die] = new_available
        if old_spent > new_total:
            warnings.append(
                _warning(
                    "hit_dice_usage_clamped",
                    f"state.hit_dice_state.{die}",
                    (
                        f"Spent {die} hit dice ({old_spent}) exceed the new total "
                        f"({new_total}); available is clamped to 0."
                    ),
                )
            )
        if old_total != new_total or old_available != new_available:
            changes.append(
                StateReconciliationChange(
                    path=f"state.hit_dice_state.{die}",
                    kind="hit_dice_capacity",
                    before=f"available={old_available}, total={old_total}",
                    after=f"available={new_available}, total={new_total}",
                    message="Preserve spent hit dice; newly gained dice become available.",
                )
            )
    for die in sorted(set(old_hit_dice_totals) - set(new_hit_dice_totals)):
        warnings.append(
            _warning(
                "hit_die_type_removed",
                f"state.hit_dice_state.{die}",
                f"The new Build no longer has {die} hit dice; the live counter is removed.",
            )
        )

    proposed = old_state.model_copy(
        update={
            "current_hp": new_current_hp,
            "spell_slots": new_spell_slots,
            "resources": new_resources,
            "hit_dice_state": new_hit_dice_state,
        }
    )

    try:
        validate_state_against_build(proposed, new_build, registry)
    except CharacterValidationError as exc:
        without_prepared = proposed.model_copy(
            update={"prepared_spell_entry_ids": [], "prepared_spells": []}
        )
        try:
            validate_state_against_build(without_prepared, new_build, registry)
        except CharacterValidationError:
            blocking.append(
                _blocking(
                    "state_reconciliation_invalid",
                    "state",
                    f"Current State cannot be reconciled to the proposed Build: {exc}",
                )
            )
        else:
            blocking.append(
                _blocking(
                    "prepared_spell_reconciliation_required",
                    "state.prepared_spells",
                    (
                        "At least one currently prepared spell is no longer legal "
                        f"under the proposed Build: {exc}"
                    ),
                )
            )

    return StateReconciliationPreview(
        proposed_state=proposed,
        changes=tuple(changes),
        blocking_issues=tuple(blocking),
        warnings=tuple(warnings),
        can_apply=not blocking,
    )
