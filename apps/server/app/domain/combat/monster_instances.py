from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal
from uuid import UUID, uuid5

from pydantic import Field, model_validator

from app.content.identity import parse_stable_key
from app.content.p4a_combat_templates import monster_to_reusable_rules
from app.content.p4a_monsters import MonsterData
from app.content.registry import ContentRegistry
from app.domain.combat.lifecycle import CombatNotFoundError
from app.domain.combat.spell_resources import monster_casting_sources
from app.domain.rooms.schemas import StrictModel
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.combat.lifecycle import (
    CombatNotFoundPersistenceError,
    actor_binding,
)
from app.persistence.combat.monster_bookkeeping import MonsterBookkeepingRepository
from app.persistence.combat.repository import (
    _UNSET,
    MonsterRepository,
    StoredMonsterInstance,
)


class MonsterRevealPatch(StrictModel):
    armor_class: bool | None = None
    description: bool | None = None
    position_note: bool | None = None


class MonsterInstancePatchInput(StrictModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    visibility: Literal["public", "hidden"] | None = None
    position_note: str | None = Field(default=None, max_length=500)
    reveal: MonsterRevealPatch | None = None
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)

    @model_validator(mode="after")
    def validate_non_empty(self) -> MonsterInstancePatchInput:
        patch_fields = self.model_fields_set - {"idempotency_key", "instance_id"}
        if not patch_fields:
            raise ValueError("at least one monster instance field or reveal toggle must be updated")
        if "reveal" in patch_fields and len(patch_fields) == 1:
            if self.reveal is None or (
                self.reveal.armor_class is None
                and self.reveal.description is None
                and self.reveal.position_note is None
            ):
                raise ValueError("at least one monster instance field or reveal toggle must be updated")
        return self


class MonsterInstanceUpdateToolInput(MonsterInstancePatchInput):
    instance_id: UUID


class QuickEnemyAttackInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    attack_bonus: int | None = None
    damage: str = Field(min_length=1, max_length=60)
    attack_kind: str | None = None


class CreateQuickEnemyInput(StrictModel):
    name: str = Field(min_length=1, max_length=120)
    armor_class: int = Field(ge=0, le=30)
    max_hp: int = Field(ge=1, le=999)
    speed: dict[str, str] = Field(default_factory=lambda: {"walk": "30 ft."})
    attack: QuickEnemyAttackInput | None = None
    visibility: Literal["public", "hidden"] = "public"
    position_note: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class CreateMonsterFromContentInput(StrictModel):
    content_key: str = Field(min_length=1)
    name: str | None = Field(default=None, max_length=120)
    visibility: Literal["public", "hidden"] = "public"
    position_note: str | None = Field(default=None, max_length=500)
    idempotency_key: str | None = Field(default=None, min_length=1, max_length=120)


class MonsterInstanceView(StrictModel):
    id: UUID
    campaign_id: UUID
    template_key: str | None
    custom_template_id: UUID | None
    name: str
    current_hp: int
    max_hp: int
    temp_hp: int
    armor_class: int | None
    conditions: list[dict[str, Any] | str] = Field(default_factory=list)
    effects: list[dict[str, Any] | str] = Field(default_factory=list)
    combat_status: str
    initiative: int | None
    reaction_available: bool
    resources: dict[str, Any] = Field(default_factory=dict)
    visibility: str
    position_note: str | None
    concentration: dict[str, Any] | None = None
    rules_snapshot: dict[str, Any] = Field(default_factory=dict)


def initial_monster_resources(rules_snapshot: Mapping[str, Any]) -> dict[str, int]:
    """Seed ``spell_slot:<level>`` counters from the same casting blocks
    ``resolve_monster_spell_source`` consumes. Innate spellcasting uses and
    recharge counters are not seeded here."""
    resources: dict[str, int] = {}
    for source in monster_casting_sources(rules_snapshot):
        slots = source.get("slots")
        if isinstance(slots, Mapping):
            for level, count in slots.items():
                if isinstance(count, int) and count > 0:
                    resources[f"spell_slot:{level}"] = count
    return resources


def stored_to_monster_instance_view(instance: StoredMonsterInstance) -> MonsterInstanceView:
    return MonsterInstanceView(
        id=instance.id,
        campaign_id=instance.campaign_id,
        template_key=instance.template_key,
        custom_template_id=instance.custom_template_id,
        name=instance.name,
        current_hp=instance.current_hp,
        max_hp=int(instance.rules_snapshot.get("max_hp", instance.current_hp)),
        temp_hp=instance.temp_hp,
        armor_class=instance.rules_snapshot.get("armor_class"),
        conditions=list(instance.conditions),
        effects=list(instance.effects),
        combat_status=instance.combat_status,
        initiative=instance.initiative,
        reaction_available=instance.reaction_available,
        resources=dict(instance.resources),
        visibility=instance.visibility,
        position_note=instance.position_note,
        concentration=dict(instance.concentration) if instance.concentration is not None else None,
        rules_snapshot=dict(instance.rules_snapshot),
    )


class MonsterInstanceService:
    def __init__(
        self,
        monster_repository: MonsterRepository,
        content_registry: ContentRegistry,
        table_event_service: TableEventService,
    ) -> None:
        self.monster_repository = monster_repository
        self.content_registry = content_registry
        self.table_event_service = table_event_service
        # Bookkeeping writes are event-backed, so they need the table event repository too.
        self.bookkeeping_repository = MonsterBookkeepingRepository(
            monster_repository.engine, table_event_service.repository,
        )

    def _require_dm(self, actor: TableActorContext) -> None:
        self.table_event_service.require_actor_current(actor)
        if not actor.is_current_dm:
            raise TableEventActorUnauthorizedError("Only the current Session DM manages Monster Instances")

    def _idempotent_instance(
        self, actor: TableActorContext, idempotency_key: str | None
    ) -> tuple[UUID | None, StoredMonsterInstance | None]:
        # Instances have no idempotency table: the key deterministically fixes the
        # instance id per Campaign so a retried create returns the existing row.
        if idempotency_key is None:
            return None, None
        instance_id = uuid5(actor.campaign_id, idempotency_key)
        existing = self.monster_repository.get_instance(instance_id)
        if existing is not None and existing.campaign_id == actor.campaign_id:
            return instance_id, existing
        return instance_id, None

    def create_from_content(
        self,
        actor: TableActorContext,
        input_data: CreateMonsterFromContentInput,
    ) -> MonsterInstanceView:
        self._require_dm(actor)
        instance_id, existing = self._idempotent_instance(actor, input_data.idempotency_key)
        if existing is not None:
            return stored_to_monster_instance_view(existing)

        entry = self.content_registry.get(input_data.content_key)
        parsed_key = parse_stable_key(entry.key)
        if parsed_key.kind != "monster":
            raise ValueError(f"content entry kind must be 'monster', got '{parsed_key.kind}'")

        rules_snapshot = monster_to_reusable_rules(MonsterData.model_validate(entry.data))
        template_key = input_data.content_key
        resources = initial_monster_resources(rules_snapshot)
        name = input_data.name.strip() if input_data.name and input_data.name.strip() else entry.name

        stored = self.monster_repository.create_instance(
            campaign_id=actor.campaign_id,
            name=name,
            rules_snapshot=rules_snapshot,
            template_key=template_key,
            instance_id=instance_id,
            resources=resources,
            visibility=input_data.visibility,
            position_note=input_data.position_note,
        )
        return stored_to_monster_instance_view(stored)

    def create_quick_enemy(
        self,
        actor: TableActorContext,
        input_data: CreateQuickEnemyInput,
    ) -> MonsterInstanceView:
        self._require_dm(actor)
        instance_id, existing = self._idempotent_instance(actor, input_data.idempotency_key)
        if existing is not None:
            return stored_to_monster_instance_view(existing)

        attack_dict: dict[str, Any] | None = None
        if input_data.attack is not None:
            attack_dict = input_data.attack.model_dump(exclude_none=True)

        stored = self.monster_repository.create_quick_enemy(
            campaign_id=actor.campaign_id,
            name=input_data.name,
            armor_class=input_data.armor_class,
            max_hp=input_data.max_hp,
            speed=input_data.speed,
            attack=attack_dict,
            visibility=input_data.visibility,
            position_note=input_data.position_note,
            instance_id=instance_id,
        )
        return stored_to_monster_instance_view(stored)

    def list_instances(self, actor: TableActorContext) -> tuple[MonsterInstanceView, ...]:
        self._require_dm(actor)
        instances = self.monster_repository.list_instances(actor.campaign_id)
        return tuple(stored_to_monster_instance_view(inst) for inst in instances)

    def update_instance(
        self,
        actor: TableActorContext,
        instance_id: UUID,
        input_data: MonsterInstancePatchInput,
    ) -> MonsterInstanceView:
        self._require_dm(actor)

        name = input_data.name if "name" in input_data.model_fields_set else _UNSET
        visibility = input_data.visibility if "visibility" in input_data.model_fields_set else _UNSET
        position_note = input_data.position_note if "position_note" in input_data.model_fields_set else _UNSET

        reveal_patch = input_data.reveal.model_dump(exclude_none=True) if input_data.reveal is not None else None

        binding = actor_binding(actor)
        try:
            stored, _event = self.bookkeeping_repository.update_instance(
                binding=binding,
                instance_id=instance_id,
                name=name,
                visibility=visibility,
                position_note=position_note,
                reveal_patch=reveal_patch,
                idempotency_key=input_data.idempotency_key,
            )
        except CombatNotFoundPersistenceError as exc:
            raise CombatNotFoundError(str(exc)) from exc

        if self.table_event_service.notifier is not None:
            self.table_event_service.notifier.notify(actor.session_id)

        return stored_to_monster_instance_view(stored)


__all__ = [
    "CreateMonsterFromContentInput",
    "CreateQuickEnemyInput",
    "MonsterInstancePatchInput",
    "MonsterInstanceService",
    "MonsterInstanceUpdateToolInput",
    "MonsterInstanceView",
    "MonsterRevealPatch",
    "QuickEnemyAttackInput",
    "initial_monster_resources",
    "stored_to_monster_instance_view",
]
