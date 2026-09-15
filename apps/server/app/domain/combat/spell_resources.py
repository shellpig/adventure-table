from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Mapping

from app.domain.character.schemas import (
    CharacterBuild,
    CharacterState,
    ResourceCounter,
    SpellAccessEntry,
    SpellcastingProfile,
)
from app.domain.rules.spellcasting import pact_resource_key


class SpellResourceKind(StrEnum):
    CANTRIP = "cantrip"
    NORMAL_SLOT = "normal_slot"
    PACT_SLOT = "pact_slot"
    FREE_USE = "free_use"


@dataclass(frozen=True)
class CharacterSpellAuthorization:
    profile: SpellcastingProfile
    access: SpellAccessEntry | None
    spell_ref: str
    spell_level: int
    slot_level: int
    resource_kind: SpellResourceKind
    resource_key: str | None


@dataclass(frozen=True)
class CharacterSpellSpend:
    authorization: CharacterSpellAuthorization
    state: CharacterState
    event: dict[str, object] | None


def _profile(build: CharacterBuild, profile_id: str) -> SpellcastingProfile:
    for profile in build.spellcasting_profiles:
        if profile.profile_id == profile_id:
            return profile
    raise ValueError(f"unknown spellcasting profile: {profile_id}")


def _matching_access(
    build: CharacterBuild, *, profile: SpellcastingProfile, spell_ref: str
) -> tuple[SpellAccessEntry, ...]:
    return tuple(
        entry
        for entry in build.spell_access_entries
        if entry.spell_key == spell_ref
        and (
            entry.source_key == profile.source_key
            or (entry.source_type == "class" and entry.source_key == profile.class_ref)
        )
    )


def authorize_character_spell(
    *,
    build: CharacterBuild,
    state: CharacterState,
    profile_id: str,
    spell_ref: str,
    spell_level: int,
    slot_level: int | None = None,
) -> CharacterSpellAuthorization:
    """Validate spell access and choose exactly one authoritative resource source.

    This function is intentionally read-only. Call ``spend_character_spell``
    only after every other cast validation succeeds, which prevents invalid
    commands from consuming resources.
    """

    if spell_level < 0 or spell_level > 9:
        raise ValueError("spell_level must be between 0 and 9")
    profile = _profile(build, profile_id)
    if spell_level > profile.max_spell_level:
        raise ValueError("spell level exceeds source profile eligibility")

    accesses = _matching_access(build, profile=profile, spell_ref=spell_ref)
    direct = next(
        (
            entry
            for entry in accesses
            if entry.access_type in {"always_prepared", "granted"}
        ),
        None,
    )
    access = direct or (accesses[0] if accesses else None)

    if direct is None:
        if profile.access_model == "known":
            if access is None or access.access_type not in {"known", "granted", "always_prepared"}:
                raise ValueError("spell is not known for this spellcasting source")
        else:
            prepared = next(
                (
                    item
                    for item in state.prepared_spells
                    if item.source_profile_id == profile.profile_id and item.spell_key == spell_ref
                ),
                None,
            )
            # Legacy Current State stored prepared access entry ids. Accept it
            # only when it resolves to a source-matching access row.
            legacy_prepared = access is not None and access.entry_id in state.prepared_spell_entry_ids
            if prepared is None and not legacy_prepared:
                raise ValueError("spell is not prepared for this spellcasting source")

    if spell_level == 0:
        if slot_level not in (None, 0):
            raise ValueError("cantrips cannot consume spell slots")
        return CharacterSpellAuthorization(
            profile=profile,
            access=access,
            spell_ref=spell_ref,
            spell_level=0,
            slot_level=0,
            resource_kind=SpellResourceKind.CANTRIP,
            resource_key=None,
        )

    if slot_level is None:
        raise ValueError("leveled spell requires slot_level")
    if slot_level < spell_level or slot_level > 9:
        raise ValueError("slot_level cannot be below spell level or above 9")

    if profile.resource_pool_type == "normal_multiclass_slots":
        counter = state.spell_slots.get(slot_level)
        if counter is None or counter.remaining <= 0:
            raise ValueError(f"no level {slot_level} normal spell slot remains")
        return CharacterSpellAuthorization(
            profile=profile,
            access=access,
            spell_ref=spell_ref,
            spell_level=spell_level,
            slot_level=slot_level,
            resource_kind=SpellResourceKind.NORMAL_SLOT,
            resource_key=str(slot_level),
        )

    pools = tuple(
        pool
        for pool in build.spell_resource_pools
        if pool.pool_type == "pact_magic" and pool.source_profile_id == profile.profile_id
    )
    if len(pools) != 1:
        raise ValueError("Pact Magic source must resolve to exactly one resource pool")
    pool = pools[0]
    capacity = next((row.capacity for row in pool.slots if row.level == slot_level), None)
    if capacity is None:
        raise ValueError(f"Pact Magic source has no level {slot_level} slot tier")
    key = pact_resource_key(pool.pool_id, slot_level)
    counter = state.resources.get(key)
    if counter is None or counter.remaining <= 0:
        raise ValueError(f"no level {slot_level} Pact Magic slot remains")
    if counter.used + counter.remaining != capacity:
        raise ValueError("Pact Magic Current State does not match Build capacity")
    return CharacterSpellAuthorization(
        profile=profile,
        access=access,
        spell_ref=spell_ref,
        spell_level=spell_level,
        slot_level=slot_level,
        resource_kind=SpellResourceKind.PACT_SLOT,
        resource_key=key,
    )


def spend_character_spell(
    *, state: CharacterState, authorization: CharacterSpellAuthorization
) -> CharacterSpellSpend:
    """Return a new CharacterState after one validated slot spend."""

    if authorization.resource_kind is SpellResourceKind.CANTRIP:
        return CharacterSpellSpend(authorization=authorization, state=state.model_copy(deep=True), event=None)

    if authorization.resource_kind is SpellResourceKind.NORMAL_SLOT:
        level = authorization.slot_level
        current = state.spell_slots.get(level)
        if current is None or current.remaining <= 0:
            raise ValueError(f"no level {level} normal spell slot remains")
        slots = dict(state.spell_slots)
        slots[level] = ResourceCounter(used=current.used + 1, remaining=current.remaining - 1)
        next_state = state.model_copy(update={"spell_slots": slots}, deep=True)
        key = f"normal:{level}"
    elif authorization.resource_kind is SpellResourceKind.PACT_SLOT:
        key = authorization.resource_key
        if key is None:
            raise ValueError("Pact Magic authorization is missing resource key")
        current = state.resources.get(key)
        if current is None or current.remaining <= 0:
            raise ValueError(f"no level {authorization.slot_level} Pact Magic slot remains")
        resources = dict(state.resources)
        resources[key] = ResourceCounter(used=current.used + 1, remaining=current.remaining - 1)
        next_state = state.model_copy(update={"resources": resources}, deep=True)
    else:
        raise ValueError(f"unsupported spell resource kind: {authorization.resource_kind}")

    return CharacterSpellSpend(
        authorization=authorization,
        state=next_state,
        event={
            "type": "spell_resource_spent",
            "spell_ref": authorization.spell_ref,
            "profile_id": authorization.profile.profile_id,
            "resource_kind": authorization.resource_kind.value,
            "resource_key": key,
            "slot_level": authorization.slot_level,
        },
    )


@dataclass(frozen=True)
class MonsterSpellSource:
    spell_ref: str
    spell_level: int
    attack_bonus: int | None
    save_dc: int | None
    resource_key: str | None


def resolve_monster_spell_source(
    *,
    rules_snapshot: Mapping[str, Any],
    resources: Mapping[str, int | ResourceCounter],
    spell_ref: str,
    spell_level: int,
    slot_level: int | None = None,
) -> MonsterSpellSource:
    """Resolve normalized Monster stat-block casting without inventing a class.

    P4-A snapshots may contain either a ``spellcasting`` mapping or an
    ``innate_spellcasting`` mapping. Both are normalized here to the same
    source contract. The caller remains responsible for atomically persisting
    the returned resource spend with the combat resolution.
    """

    casting = rules_snapshot.get("spellcasting")
    if not isinstance(casting, Mapping):
        casting = rules_snapshot.get("innate_spellcasting")
    if not isinstance(casting, Mapping):
        raise ValueError("monster stat block has no spellcasting source")

    spells = casting.get("spells")
    if not isinstance(spells, (list, tuple)):
        raise ValueError("monster spellcasting source has no normalized spells")
    row: Mapping[str, Any] | None = None
    for candidate in spells:
        if isinstance(candidate, str) and candidate == spell_ref:
            row = {"spell_ref": candidate, "level": spell_level}
            break
        if isinstance(candidate, Mapping) and candidate.get("spell_ref") == spell_ref:
            row = candidate
            break
    if row is None:
        raise ValueError("monster does not have requested spell")
    declared_level = row.get("level", spell_level)
    if not isinstance(declared_level, int) or declared_level != spell_level:
        raise ValueError("monster spell level does not match stat block")

    resource_key: str | None = None
    if spell_level > 0:
        effective_slot = slot_level if slot_level is not None else spell_level
        if effective_slot < spell_level:
            raise ValueError("monster slot level cannot be below spell level")
        explicit = row.get("resource_key")
        resource_key = str(explicit) if isinstance(explicit, str) and explicit else f"spell_slot:{effective_slot}"
        counter = resources.get(resource_key)
        remaining = counter.remaining if isinstance(counter, ResourceCounter) else counter
        if not isinstance(remaining, int) or remaining <= 0:
            raise ValueError(f"monster spell resource is unavailable: {resource_key}")

    attack_bonus = casting.get("attack_bonus")
    save_dc = casting.get("save_dc")
    return MonsterSpellSource(
        spell_ref=spell_ref,
        spell_level=spell_level,
        attack_bonus=int(attack_bonus) if isinstance(attack_bonus, int) else None,
        save_dc=int(save_dc) if isinstance(save_dc, int) else None,
        resource_key=resource_key,
    )
