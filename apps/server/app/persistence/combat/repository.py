from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import insert, select, update
from sqlalchemy.engine import Engine

from app.content.p4a_combat_templates import (
    MonsterActionNormalizationError,
    normalize_monster_action,
)
from app.persistence.combat.tables import monster_instances, monster_templates


class MonsterPersistenceError(ValueError):
    pass


_UNSET = object()


@dataclass(frozen=True)
class StoredMonsterTemplate:
    id: UUID
    campaign_id: UUID
    name: str
    source_key: str | None
    rules: dict[str, Any]
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True)
class StoredMonsterInstance:
    id: UUID
    campaign_id: UUID
    template_key: str | None
    custom_template_id: UUID | None
    name: str
    rules_snapshot: dict[str, Any]
    current_hp: int
    temp_hp: int
    conditions: list[dict[str, Any] | str]
    effects: list[dict[str, Any] | str]
    combat_status: str
    initiative: int | None
    reaction_available: bool
    resources: dict[str, Any]
    visibility: str
    position_note: str | None
    created_at: datetime
    updated_at: datetime


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_rules(rules: dict[str, Any]) -> dict[str, Any]:
    required = ("armor_class", "max_hp", "speed")
    missing = [key for key in required if key not in rules]
    if missing:
        raise MonsterPersistenceError(
            "monster rules are missing required fields: " + ", ".join(missing)
        )
    if not isinstance(rules["armor_class"], int) or rules["armor_class"] < 0:
        raise MonsterPersistenceError("monster armor_class must be a non-negative integer")
    if not isinstance(rules["max_hp"], int) or rules["max_hp"] < 0:
        raise MonsterPersistenceError("monster max_hp must be a non-negative integer")
    if not isinstance(rules["speed"], dict) or not rules["speed"]:
        raise MonsterPersistenceError("monster speed must be a non-empty object")
    return deepcopy(rules)


def _template_from_row(row: Any) -> StoredMonsterTemplate:
    values = dict(row)
    values["rules"] = deepcopy(values["rules"])
    return StoredMonsterTemplate(**values)


def _instance_from_row(row: Any) -> StoredMonsterInstance:
    values = dict(row)
    values["rules_snapshot"] = deepcopy(values["rules_snapshot"])
    values["conditions"] = deepcopy(values["conditions"])
    values["effects"] = deepcopy(values["effects"])
    values["resources"] = deepcopy(values["resources"])
    return StoredMonsterInstance(**values)


class MonsterRepository:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    def create_template(
        self,
        *,
        campaign_id: UUID,
        name: str,
        rules: dict[str, Any],
        source_key: str | None = None,
        template_id: UUID | None = None,
        now: datetime | None = None,
    ) -> StoredMonsterTemplate:
        if not name.strip():
            raise MonsterPersistenceError("monster template name must not be blank")
        moment = now or _now()
        values = {
            "id": template_id or uuid4(),
            "campaign_id": campaign_id,
            "name": name.strip(),
            "source_key": source_key,
            "rules": _validate_rules(rules),
            "created_at": moment,
            "updated_at": moment,
        }
        with self.engine.begin() as connection:
            connection.execute(insert(monster_templates).values(**values))
        return StoredMonsterTemplate(**deepcopy(values))

    def create_instance(
        self,
        *,
        campaign_id: UUID,
        name: str,
        rules_snapshot: dict[str, Any],
        template_key: str | None = None,
        custom_template_id: UUID | None = None,
        instance_id: UUID | None = None,
        current_hp: int | None = None,
        temp_hp: int = 0,
        conditions: list[dict[str, Any] | str] | None = None,
        effects: list[dict[str, Any] | str] | None = None,
        combat_status: str = "active",
        initiative: int | None = None,
        reaction_available: bool = True,
        resources: dict[str, Any] | None = None,
        visibility: str = "public",
        position_note: str | None = None,
        now: datetime | None = None,
    ) -> StoredMonsterInstance:
        if template_key is not None and custom_template_id is not None:
            raise MonsterPersistenceError("monster instance may have only one template source")
        if custom_template_id is not None:
            template = self.get_template(custom_template_id)
            if template is None:
                raise MonsterPersistenceError(f"monster template not found: {custom_template_id}")
            if template.campaign_id != campaign_id:
                raise MonsterPersistenceError("monster template and instance must belong to the same campaign")
        if not name.strip():
            raise MonsterPersistenceError("monster instance name must not be blank")
        rules = _validate_rules(rules_snapshot)
        hp = rules["max_hp"] if current_hp is None else current_hp
        if hp < 0 or temp_hp < 0:
            raise MonsterPersistenceError("monster HP values must not be negative")
        if combat_status not in {"active", "down", "dead", "removed"}:
            raise MonsterPersistenceError(f"unsupported combat status: {combat_status}")
        if visibility not in {"public", "hidden"}:
            raise MonsterPersistenceError(f"unsupported monster visibility: {visibility}")
        moment = now or _now()
        values = {
            "id": instance_id or uuid4(),
            "campaign_id": campaign_id,
            "template_key": template_key,
            "custom_template_id": custom_template_id,
            "name": name.strip(),
            "rules_snapshot": rules,
            "current_hp": hp,
            "temp_hp": temp_hp,
            "conditions": deepcopy(conditions or []),
            "effects": deepcopy(effects or []),
            "combat_status": combat_status,
            "initiative": initiative,
            "reaction_available": reaction_available,
            "resources": deepcopy(resources or {}),
            "visibility": visibility,
            "position_note": position_note,
            "created_at": moment,
            "updated_at": moment,
        }
        with self.engine.begin() as connection:
            connection.execute(insert(monster_instances).values(**values))
        return StoredMonsterInstance(**deepcopy(values))

    def create_quick_enemy(
        self,
        *,
        campaign_id: UUID,
        name: str,
        armor_class: int,
        max_hp: int,
        speed: dict[str, str],
        attack: dict[str, Any] | None = None,
        visibility: str = "public",
        position_note: str | None = None,
        instance_id: UUID | None = None,
        now: datetime | None = None,
    ) -> StoredMonsterInstance:
        rules: dict[str, Any] = {
            "armor_class": armor_class,
            "max_hp": max_hp,
            "speed": deepcopy(speed),
        }
        if attack is not None:
            try:
                quick_attack = deepcopy(attack)
                quick_attack.setdefault("attack_kind", "melee_weapon")
                rules["actions"] = [normalize_monster_action(quick_attack)]
            except MonsterActionNormalizationError as exc:
                raise MonsterPersistenceError(f"invalid quick enemy attack: {exc}") from exc
        return self.create_instance(
            campaign_id=campaign_id,
            name=name,
            rules_snapshot=rules,
            visibility=visibility,
            position_note=position_note,
            instance_id=instance_id,
            now=now,
        )

    def create_instance_from_template(
        self,
        template_id: UUID,
        *,
        name: str | None = None,
        instance_id: UUID | None = None,
        now: datetime | None = None,
    ) -> StoredMonsterInstance:
        template = self.get_template(template_id)
        if template is None:
            raise MonsterPersistenceError(f"monster template not found: {template_id}")
        return self.create_instance(
            campaign_id=template.campaign_id,
            name=name or template.name,
            rules_snapshot=template.rules,
            custom_template_id=template.id,
            instance_id=instance_id,
            now=now,
        )

    def save_instance_as_template(
        self,
        instance_id: UUID,
        *,
        name: str | None = None,
        template_id: UUID | None = None,
        now: datetime | None = None,
    ) -> StoredMonsterTemplate:
        instance = self.get_instance(instance_id)
        if instance is None:
            raise MonsterPersistenceError(f"monster instance not found: {instance_id}")
        return self.create_template(
            campaign_id=instance.campaign_id,
            name=name or instance.name,
            rules=instance.rules_snapshot,
            source_key=instance.template_key,
            template_id=template_id,
            now=now,
        )

    def get_template(self, template_id: UUID) -> StoredMonsterTemplate | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(monster_templates).where(monster_templates.c.id == template_id)
            ).mappings().one_or_none()
        return _template_from_row(row) if row is not None else None

    def get_instance(self, instance_id: UUID) -> StoredMonsterInstance | None:
        with self.engine.connect() as connection:
            row = connection.execute(
                select(monster_instances).where(monster_instances.c.id == instance_id)
            ).mappings().one_or_none()
        return _instance_from_row(row) if row is not None else None

    def list_instances(self, campaign_id: UUID) -> list[StoredMonsterInstance]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                select(monster_instances)
                .where(monster_instances.c.campaign_id == campaign_id)
                .order_by(monster_instances.c.created_at, monster_instances.c.id)
            ).mappings().all()
        return [_instance_from_row(row) for row in rows]

    def update_live_state(
        self,
        instance_id: UUID,
        *,
        current_hp: int | None = None,
        temp_hp: int | None = None,
        conditions: list[dict[str, Any] | str] | None = None,
        effects: list[dict[str, Any] | str] | None = None,
        combat_status: str | None = None,
        initiative: int | None | object = _UNSET,
        reaction_available: bool | None = None,
        resources: dict[str, Any] | None = None,
        visibility: str | None = None,
        position_note: str | None | object = _UNSET,
        now: datetime | None = None,
    ) -> StoredMonsterInstance:
        values: dict[str, Any] = {"updated_at": now or _now()}
        if current_hp is not None:
            if current_hp < 0:
                raise MonsterPersistenceError("monster current_hp must not be negative")
            values["current_hp"] = current_hp
        if temp_hp is not None:
            if temp_hp < 0:
                raise MonsterPersistenceError("monster temp_hp must not be negative")
            values["temp_hp"] = temp_hp
        if conditions is not None:
            values["conditions"] = deepcopy(conditions)
        if effects is not None:
            values["effects"] = deepcopy(effects)
        if combat_status is not None:
            if combat_status not in {"active", "down", "dead", "removed"}:
                raise MonsterPersistenceError(f"unsupported combat status: {combat_status}")
            values["combat_status"] = combat_status
        if initiative is not _UNSET:
            values["initiative"] = initiative
        if reaction_available is not None:
            values["reaction_available"] = reaction_available
        if resources is not None:
            values["resources"] = deepcopy(resources)
        if visibility is not None:
            if visibility not in {"public", "hidden"}:
                raise MonsterPersistenceError(f"unsupported monster visibility: {visibility}")
            values["visibility"] = visibility
        if position_note is not _UNSET:
            values["position_note"] = position_note
        with self.engine.begin() as connection:
            result = connection.execute(
                update(monster_instances)
                .where(monster_instances.c.id == instance_id)
                .values(**values)
            )
        if result.rowcount != 1:
            raise MonsterPersistenceError(f"monster instance not found: {instance_id}")
        stored = self.get_instance(instance_id)
        assert stored is not None
        return stored


__all__ = [
    "MonsterPersistenceError",
    "MonsterRepository",
    "StoredMonsterInstance",
    "StoredMonsterTemplate",
]
