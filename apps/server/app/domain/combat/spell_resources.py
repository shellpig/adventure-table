from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
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


@dataclass(frozen=True)
class MonsterSpellSpend:
    source: MonsterSpellSource
    resources: dict[str, int | ResourceCounter]
    event: dict[str, object] | None


def _slug(value: str) -> str:
    value = value.strip().lower()
    if "/" in value:
        value = value.rstrip("/").rsplit("/", 1)[-1]
    if ":" in value:
        value = value.rsplit(":", 1)[-1]
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


def monster_casting_sources(rules_snapshot: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    """Return every spellcasting block accepted from P4-A snapshots.

    P4-A stores SRD API trait payloads under ``traits[].spellcasting`` (or the
    innate equivalent). The older top-level normalized form remains accepted
    so persisted pre-P4-D fixtures continue to load.
    """

    found: list[Mapping[str, Any]] = []
    for key in ("spellcasting", "innate_spellcasting"):
        value = rules_snapshot.get(key)
        if isinstance(value, Mapping):
            found.append(value)

    traits = rules_snapshot.get("traits")
    if isinstance(traits, (list, tuple)):
        for trait in traits:
            if not isinstance(trait, Mapping):
                continue
            for key in ("spellcasting", "innate_spellcasting"):
                value = trait.get(key)
                if isinstance(value, Mapping):
                    found.append(value)
    return tuple(found)


def _monster_spell_matches(candidate: object, spell_ref: str) -> Mapping[str, Any] | None:
    requested_slug = _slug(spell_ref)
    if isinstance(candidate, str):
        return {"spell_ref": candidate} if _slug(candidate) == requested_slug else None
    if not isinstance(candidate, Mapping):
        return None
    values = (
        candidate.get("spell_ref"),
        candidate.get("url"),
        candidate.get("name"),
    )
    if any(isinstance(value, str) and _slug(value) == requested_slug for value in values):
        return candidate
    return None


def resolve_monster_spell_source(
    *,
    rules_snapshot: Mapping[str, Any],
    resources: Mapping[str, int | ResourceCounter],
    spell_ref: str,
    spell_level: int,
    slot_level: int | None = None,
) -> MonsterSpellSource:
    """Resolve a spell against the real P4-A Monster rules snapshot.

    SRD monster snapshots preserve the upstream shape under
    ``traits[].spellcasting``: spells use ``name``/``url`` while spellcasting
    attack/DC values use ``modifier``/``dc``. Older normalized fields remain
    readable for backward compatibility; they are not required for new data.
    """

    if spell_level < 0 or spell_level > 9:
        raise ValueError("spell_level must be between 0 and 9")

    matched_casting: Mapping[str, Any] | None = None
    row: Mapping[str, Any] | None = None
    for casting in monster_casting_sources(rules_snapshot):
        spells = casting.get("spells")
        if not isinstance(spells, (list, tuple)):
            continue
        for candidate in spells:
            matched = _monster_spell_matches(candidate, spell_ref)
            if matched is not None:
                matched_casting = casting
                row = matched
                break
        if row is not None:
            break

    if not monster_casting_sources(rules_snapshot):
        raise ValueError("monster stat block has no spellcasting source")
    if row is None or matched_casting is None:
        raise ValueError("monster does not have requested spell")

    declared_level = row.get("level")
    if declared_level is not None:
        try:
            normalized_level = int(declared_level)
        except (TypeError, ValueError) as exc:
            raise ValueError("monster spell level is invalid") from exc
        if normalized_level != spell_level:
            raise ValueError("monster spell level does not match stat block")

    resource_key: str | None = None
    if spell_level > 0:
        effective_slot = slot_level if slot_level is not None else spell_level
        if effective_slot < spell_level:
            raise ValueError("monster slot level cannot be below spell level")

        declared_slots = matched_casting.get("slots")
        if isinstance(declared_slots, Mapping):
            declared_capacity = declared_slots.get(str(effective_slot), declared_slots.get(effective_slot))
            if declared_capacity is None:
                raise ValueError(f"monster stat block has no level {effective_slot} spell slots")

        explicit = row.get("resource_key")
        resource_key = (
            str(explicit)
            if isinstance(explicit, str) and explicit
            else f"spell_slot:{effective_slot}"
        )
        counter = resources.get(resource_key)
        remaining = counter.remaining if isinstance(counter, ResourceCounter) else counter
        if not isinstance(remaining, int) or remaining <= 0:
            raise ValueError(f"monster spell resource is unavailable: {resource_key}")

    attack_bonus = matched_casting.get("attack_bonus", matched_casting.get("modifier"))
    save_dc = matched_casting.get("save_dc", matched_casting.get("dc"))
    return MonsterSpellSource(
        spell_ref=spell_ref,
        spell_level=spell_level,
        attack_bonus=int(attack_bonus) if isinstance(attack_bonus, int) else None,
        save_dc=int(save_dc) if isinstance(save_dc, int) else None,
        resource_key=resource_key,
    )


def spend_monster_spell(
    *,
    resources: Mapping[str, int | ResourceCounter],
    source: MonsterSpellSource,
) -> MonsterSpellSpend:
    """Spend a previously authorized monster spell resource without mutating input."""

    next_resources: dict[str, int | ResourceCounter] = dict(resources)
    if source.resource_key is None:
        return MonsterSpellSpend(source=source, resources=next_resources, event=None)

    current = resources.get(source.resource_key)
    if isinstance(current, ResourceCounter):
        if current.remaining <= 0:
            raise ValueError(f"monster spell resource is unavailable: {source.resource_key}")
        next_resources[source.resource_key] = ResourceCounter(
            used=current.used + 1,
            remaining=current.remaining - 1,
        )
    elif isinstance(current, int):
        if current <= 0:
            raise ValueError(f"monster spell resource is unavailable: {source.resource_key}")
        next_resources[source.resource_key] = current - 1
    else:
        raise ValueError(f"monster spell resource is unavailable: {source.resource_key}")

    return MonsterSpellSpend(
        source=source,
        resources=next_resources,
        event={
            "type": "monster_spell_resource_spent",
            "spell_ref": source.spell_ref,
            "resource_key": source.resource_key,
        },
    )
