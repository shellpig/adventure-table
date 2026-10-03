from __future__ import annotations

from copy import deepcopy
from typing import Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Engine

from app.persistence.rooms.tables import campaigns

from app.content.identity import parse_stable_key
from app.content.localization import ContentLocalizationCatalog
from app.content.p4a_combat_templates import (
    monster_to_reusable_rules,
    normalize_monster_action,
)
from app.content.p4a_monsters import MonsterData
from app.content.registry import ContentNotFoundError, ContentRegistry, ContentValidationError
from app.content.schemas import ContentEntry
from app.domain.monster_library.errors import (
    InvalidMonsterRulesError,
    InvalidMonsterTemplateRefError,
    MonsterLibraryForbiddenError,
    MonsterTemplateNotFoundError,
    MonsterTemplateReadOnlyError,
    MonsterTemplateReferencedError,
    MonsterTemplateRevisionConflictError,
)
from app.domain.monster_library.references import is_monster_template_referenced
from app.domain.monster_library.schemas import (
    ArchiveCustomMonsterInput,
    CopyCustomMonsterInput,
    CreateCustomMonsterFromContentInput,
    CreateCustomMonsterFromInstanceInput,
    CreateCustomMonsterInput,
    CustomMonsterActionInput,
    CustomMonsterTraitInput,
    MonsterLibraryDetailView,
    MonsterLibrarySummaryView,
    PatchCustomMonsterInput,
)
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.table_events import (
    TableActorContext,
    TableEventActorUnauthorizedError,
    TableEventService,
)
from app.persistence.combat.repository import MonsterRepository, StoredMonsterTemplate
from app.persistence.monster_library.repository import MonsterLibraryRepository


def _resolve_name_is_custom(presentation: dict[str, object] | None) -> bool:
    if not presentation:
        return True
    return bool(presentation.get("name_is_custom", True))


def _normalize_actions_collection(
    value: Sequence[CustomMonsterActionInput | dict[str, object]] | None,
) -> list[dict[str, object]]:
    if not value:
        return []
    res: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, CustomMonsterActionInput):
            raw = item.model_dump(exclude_none=True)
            if "desc" not in raw and "description" in raw:
                raw["desc"] = raw.pop("description")
        elif isinstance(item, dict):
            raw = dict(item)
            if "desc" not in raw and "description" in raw:
                raw["desc"] = raw.pop("description")
        else:
            raise InvalidMonsterRulesError("monster action entries must be objects")
        try:
            res.append(normalize_monster_action(raw))
        except Exception as exc:
            raise InvalidMonsterRulesError(f"invalid monster action: {exc}") from exc
    return res


def _normalize_traits_collection(
    value: Sequence[CustomMonsterTraitInput | dict[str, object]] | None,
) -> list[dict[str, object]]:
    if not value:
        return []
    res: list[dict[str, object]] = []
    for item in value:
        if isinstance(item, CustomMonsterTraitInput):
            raw = item.model_dump(exclude_none=True)
        elif isinstance(item, dict):
            raw = dict(item)
        else:
            raise InvalidMonsterRulesError("monster trait entries must be objects")
        name = raw.get("name")
        if not name or not isinstance(name, str) or not name.strip():
            raise InvalidMonsterRulesError("monster trait name must not be blank")
        t_dict: dict[str, object] = {"name": name.strip()}
        desc = raw.get("desc") if raw.get("desc") is not None else raw.get("description")
        if desc is not None:
            t_dict["desc"] = str(desc)
        for extra in (
            "attack_bonus",
            "damage",
            "dc",
            "usage",
            "spellcasting",
        ):
            if extra in raw and raw[extra] is not None:
                t_dict[extra] = raw[extra]
        res.append(t_dict)
    return res


class MonsterLibraryService:
    def __init__(
        self,
        engine: Engine,
        repository: MonsterLibraryRepository,
        monster_repository: MonsterRepository,
        content_registry: ContentRegistry,
        localization: ContentLocalizationCatalog,
        table_event_service: TableEventService,
    ) -> None:
        self.engine = engine
        self.repository = repository
        self.monster_repository = monster_repository
        self.content_registry = content_registry
        self.localization = localization
        self.table_event_service = table_event_service

    @staticmethod
    def _require_room_authority(context: RoomAccessContext, room_id: UUID) -> None:
        if context.room_id != room_id:
            raise MonsterTemplateNotFoundError(f"Room '{room_id}' not found")
        if context.authority is RoomAccessAuthority.MEMBER:
            raise MonsterLibraryForbiddenError("Owner or DM authority is required to manage monster library")

    def _require_actor_dm(self, actor: TableActorContext, room_id: UUID) -> None:
        if actor.room_id != room_id:
            raise MonsterTemplateNotFoundError(f"Room '{room_id}' not found")
        self.table_event_service.require_actor_current(actor)
        if not (actor.role == "dm" and actor.is_current_dm):
            raise TableEventActorUnauthorizedError("Only the current Session DM can view the monster library")

    def _resolve_overlay_string(self, key: str, field_path: str, locale: str) -> str | None:
        try:
            field = self.localization.resolve_field(key, field_path, locale)
            if field.source == "overlay" and isinstance(field.value, str) and field.value.strip():
                return field.value.strip()
            return None
        except (ContentValidationError, KeyError):
            return None

    def _build_builtin_presentation(
        self,
        entry: ContentEntry,
        rules: dict[str, object],
    ) -> dict[str, object]:
        zh_name = self._resolve_overlay_string(entry.key, "name", "zh-TW")
        names: dict[str, str] = {"en": entry.name}
        if zh_name:
            names["zh-TW"] = zh_name

        overlay_group_paths: tuple[tuple[str, str], ...] = (
            ("traits", "data.special_abilities"),
            ("actions", "data.actions"),
            ("bonus_actions", "data.bonus_actions"),
            ("reactions", "data.reactions"),
            ("legendary_actions", "data.legendary_actions"),
        )

        ability_names: dict[str, list[dict[str, str]]] = {}
        for group, overlay_prefix in overlay_group_paths:
            items = rules.get(group)
            if isinstance(items, list):
                group_list: list[dict[str, str]] = []
                for i, ability in enumerate(items):
                    if isinstance(ability, dict):
                        en_name = str(ability.get("name", ""))
                        item: dict[str, str] = {"en": en_name}
                        zh_ability = self._resolve_overlay_string(
                            entry.key, f"{overlay_prefix}.{i}.name", "zh-TW"
                        )
                        if zh_ability:
                            item["zh-TW"] = zh_ability
                        group_list.append(item)
                ability_names[group] = group_list

        return {
            "names": names,
            "name_is_custom": False,
            "ability_names": ability_names,
            "desc_is_english": True,
        }

    def _matches_builtin_query(self, entry: ContentEntry, normalized_query: str | None) -> bool:
        if normalized_query is None:
            return True
        zh_name = self._resolve_overlay_string(entry.key, "name", "zh-TW")
        data = entry.data if isinstance(entry.data, dict) else {}
        m_type = str(data.get("type", ""))
        subtype = str(data.get("subtype", ""))
        return (
            normalized_query in entry.name.casefold()
            or (zh_name is not None and normalized_query in zh_name.casefold())
            or normalized_query in m_type.casefold()
            or (bool(subtype) and normalized_query in subtype.casefold())
        )

    @staticmethod
    def _to_detail_view(stored: StoredMonsterTemplate) -> MonsterLibraryDetailView:
        presentation = dict(stored.presentation_json)
        names = dict(presentation.get("names", {})) if isinstance(presentation.get("names"), dict) else {}
        name_is_custom = _resolve_name_is_custom(presentation)
        return MonsterLibraryDetailView(
            ref=f"custom:{stored.id}",
            name=stored.name,
            names=names,
            name_is_custom=name_is_custom,
            source_kind="custom",
            source_key=stored.source_key,
            rules=dict(stored.rules),
            presentation=presentation,
            revision=stored.revision,
            archived_at=stored.archived_at,
            created_at=stored.created_at,
            updated_at=stored.updated_at,
        )

    def list(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        *,
        query: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
        source: str = "all",
    ) -> list[MonsterLibrarySummaryView]:
        self._require_room_authority(context, room_id)
        return self._list_internal(
            room_id=room_id,
            query=query,
            include_archived=include_archived,
            limit=limit,
            offset=offset,
            source=source,
        )

    def list_for_actor(
        self,
        actor: TableActorContext,
        room_id: UUID,
        *,
        query: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[MonsterLibrarySummaryView]:
        self._require_actor_dm(actor, room_id)
        return self._list_internal(
            room_id=room_id,
            query=query,
            include_archived=False,
            limit=limit,
            offset=offset,
            source="all",
        )

    def _list_internal(
        self,
        *,
        room_id: UUID,
        query: str | None = None,
        include_archived: bool = False,
        limit: int = 50,
        offset: int = 0,
        source: str = "all",
    ) -> list[MonsterLibrarySummaryView]:
        normalized_query = query.strip().casefold() if query is not None and query.strip() else None

        def _custom_to_summary(custom: StoredMonsterTemplate) -> MonsterLibrarySummaryView:
            presentation = dict(custom.presentation_json)
            names = dict(presentation.get("names", {})) if isinstance(presentation.get("names"), dict) else {}
            name_is_custom = _resolve_name_is_custom(presentation)
            rules = custom.rules if isinstance(custom.rules, dict) else {}
            size = str(rules["size"]) if "size" in rules and rules["size"] is not None else None
            monster_type = str(rules["type"]) if "type" in rules and rules["type"] is not None else None
            alignment = str(rules["alignment"]) if "alignment" in rules and rules["alignment"] is not None else None
            ac_raw = rules.get("armor_class")
            ac = int(ac_raw) if isinstance(ac_raw, int) else None
            max_hp_raw = rules.get("max_hp")
            max_hp = int(max_hp_raw) if isinstance(max_hp_raw, int) else None
            cr_raw = rules.get("challenge_rating")
            cr = float(cr_raw) if isinstance(cr_raw, (int, float)) else None
            return MonsterLibrarySummaryView(
                ref=f"custom:{custom.id}",
                name=custom.name,
                names=names,
                name_is_custom=name_is_custom,
                source_kind="custom",
                source_key=custom.source_key,
                size=size,
                type=monster_type,
                alignment=alignment,
                armor_class=ac,
                max_hp=max_hp,
                challenge_rating=cr,
                archived_at=custom.archived_at,
                revision=custom.revision,
            )

        def _builtin_to_summary(entry: ContentEntry) -> MonsterLibrarySummaryView:
            zh_name = self._resolve_overlay_string(entry.key, "name", "zh-TW")
            names: dict[str, str] = {"en": entry.name}
            if zh_name:
                names["zh-TW"] = zh_name
            data = entry.data if isinstance(entry.data, dict) else {}
            size = str(data["size"]) if "size" in data and data["size"] is not None else None
            monster_type = str(data["type"]) if "type" in data and data["type"] is not None else None
            alignment = str(data["alignment"]) if "alignment" in data and data["alignment"] is not None else None
            ac_options = data.get("armor_class")
            ac: int | None = None
            if isinstance(ac_options, list) and ac_options and isinstance(ac_options[0], dict):
                ac_val = ac_options[0].get("value")
                if isinstance(ac_val, int):
                    ac = ac_val
            max_hp_val = data.get("hit_points")
            max_hp = int(max_hp_val) if isinstance(max_hp_val, int) else None
            cr_val = data.get("challenge_rating")
            cr = float(cr_val) if isinstance(cr_val, (int, float)) else None
            return MonsterLibrarySummaryView(
                ref=entry.key,
                name=entry.name,
                names=names,
                name_is_custom=False,
                source_kind="builtin",
                source_key=entry.key,
                size=size,
                type=monster_type,
                alignment=alignment,
                armor_class=ac,
                max_hp=max_hp,
                challenge_rating=cr,
                archived_at=None,
                revision=None,
            )

        if source == "custom":
            stored_custom = self.repository.list_custom_templates(
                room_id,
                include_archived=include_archived,
                query=query,
                limit=limit,
                offset=offset,
            )
            return [_custom_to_summary(c) for c in stored_custom]

        if source == "builtin":
            builtin_entries = self.content_registry.list_kind("monster")
            matched_builtin = [
                entry for entry in builtin_entries
                if self._matches_builtin_query(entry, normalized_query)
            ]
            matched_builtin.sort(key=lambda e: (e.name.casefold(), e.key))
            return [_builtin_to_summary(e) for e in matched_builtin[offset : offset + limit]]

        # source == "all": Bounded fetch
        stored_custom = self.repository.list_custom_templates(
            room_id,
            include_archived=include_archived,
            query=query,
            limit=offset + limit,
            offset=0,
        )
        custom_items = [_custom_to_summary(c) for c in stored_custom]

        builtin_entries = self.content_registry.list_kind("monster")
        builtin_items = [
            _builtin_to_summary(entry)
            for entry in builtin_entries
            if self._matches_builtin_query(entry, normalized_query)
        ]

        merged = custom_items + builtin_items
        merged.sort(key=lambda item: (item.name.casefold(), item.ref))
        return merged[offset : offset + limit]

    def get(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        ref: str,
    ) -> MonsterLibraryDetailView:
        self._require_room_authority(context, room_id)
        return self._get_internal(room_id=room_id, ref=ref)

    def get_for_actor(
        self,
        actor: TableActorContext,
        room_id: UUID,
        ref: str,
    ) -> MonsterLibraryDetailView:
        self._require_actor_dm(actor, room_id)
        return self._get_internal(room_id=room_id, ref=ref)

    def _get_internal(
        self,
        *,
        room_id: UUID,
        ref: str,
    ) -> MonsterLibraryDetailView:
        normalized_ref = ref.strip()
        if normalized_ref.startswith("custom:"):
            raw_uuid = normalized_ref.removeprefix("custom:").strip()
            try:
                template_id = UUID(raw_uuid)
            except ValueError as exc:
                raise InvalidMonsterTemplateRefError(f"invalid custom template ref: '{ref}'") from exc

            stored = self.repository.get_custom_template(room_id, template_id)
            if stored is None:
                raise MonsterTemplateNotFoundError(
                    f"monster template '{template_id}' not found in room '{room_id}'"
                )
            return self._to_detail_view(stored)

        # Built-in template lookup
        try:
            entry = self.content_registry.get(normalized_ref)
        except ContentNotFoundError as exc:
            raise MonsterTemplateNotFoundError(f"monster content '{ref}' not found") from exc

        parsed = parse_stable_key(entry.key)
        if parsed.kind != "monster":
            raise MonsterTemplateNotFoundError(f"content '{ref}' is not a monster")

        monster_data = MonsterData.model_validate(entry.data)
        rules = monster_to_reusable_rules(monster_data)

        presentation = self._build_builtin_presentation(entry, rules)

        return MonsterLibraryDetailView(
            ref=entry.key,
            name=entry.name,
            names=dict(presentation.get("names", {})),
            name_is_custom=False,
            source_kind="builtin",
            source_key=entry.key,
            rules=rules,
            presentation=presentation,
            revision=None,
            archived_at=None,
            created_at=None,
            updated_at=None,
        )

    def create_custom(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        payload: CreateCustomMonsterInput,
    ) -> MonsterLibraryDetailView:
        self._require_room_authority(context, room_id)

        speed_dict = {"walk": payload.speed} if isinstance(payload.speed, str) else payload.speed
        actions_list = _normalize_actions_collection(payload.actions)
        traits_list = _normalize_traits_collection(payload.traits)

        rules: dict[str, object] = {
            "name": payload.name,
            "size": payload.size,
            "type": payload.type,
            "alignment": payload.alignment,
            "armor_class": payload.armor_class,
            "max_hp": payload.max_hp,
            "speed": speed_dict,
            "hit_dice": payload.hit_dice or f"{max(1, payload.max_hp // 8)}d8",
            "hit_points_roll": payload.hit_points_roll or str(payload.max_hp),
            "ability_scores": payload.ability_scores or {
                "strength": 10,
                "dexterity": 10,
                "constitution": 10,
                "intelligence": 10,
                "wisdom": 10,
                "charisma": 10,
            },
            "proficiencies": payload.proficiencies or [],
            "damage_vulnerabilities": payload.damage_vulnerabilities or [],
            "damage_resistances": payload.damage_resistances or [],
            "damage_immunities": payload.damage_immunities or [],
            "condition_immunities": payload.condition_immunities or [],
            "senses": payload.senses or {"passive_perception": 10},
            "languages": payload.languages or "",
            "challenge_rating": payload.challenge_rating,
            "xp": payload.xp,
            "traits": traits_list,
            "actions": actions_list,
            "bonus_actions": _normalize_actions_collection(payload.bonus_actions),
            "reactions": _normalize_actions_collection(payload.reactions),
            "legendary_actions": _normalize_actions_collection(payload.legendary_actions),
        }
        if payload.description is not None:
            rules["description"] = payload.description

        presentation_json: dict[str, object] = {
            "names": {},
            "name_is_custom": True,
        }

        stored = self.repository.create_custom_template(
            room_id=room_id,
            name=payload.name,
            rules=rules,
            source_key=None,
            presentation_json=presentation_json,
        )
        return self._to_detail_view(stored)

    def create_from_content(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        payload: CreateCustomMonsterFromContentInput,
    ) -> MonsterLibraryDetailView:
        self._require_room_authority(context, room_id)

        try:
            entry = self.content_registry.get(payload.content_key)
        except ContentNotFoundError as exc:
            raise MonsterTemplateNotFoundError(f"content '{payload.content_key}' not found") from exc

        parsed = parse_stable_key(entry.key)
        if parsed.kind != "monster":
            raise MonsterTemplateNotFoundError(f"content '{payload.content_key}' is not a monster")

        monster_data = MonsterData.model_validate(entry.data)
        rules = monster_to_reusable_rules(monster_data)
        builtin_presentation = self._build_builtin_presentation(entry, rules)

        presentation_json = deepcopy(builtin_presentation)
        if payload.name and payload.name.strip():
            name = payload.name.strip()
            names: dict[str, str] = {}
            name_is_custom = True
            rules["name"] = name
        else:
            name = entry.name
            names = dict(builtin_presentation.get("names", {}))
            name_is_custom = False

        presentation_json["names"] = names
        presentation_json["name_is_custom"] = name_is_custom

        stored = self.repository.create_custom_template(
            room_id=room_id,
            name=name,
            rules=rules,
            source_key=payload.content_key,
            presentation_json=presentation_json,
        )
        return self._to_detail_view(stored)

    def _resolve_custom_template_id(self, template_id: UUID | str) -> UUID:
        if isinstance(template_id, UUID):
            return template_id
        normalized = template_id.strip()
        if normalized.startswith("custom:"):
            normalized = normalized.removeprefix("custom:").strip()
        try:
            return UUID(normalized)
        except ValueError:
            try:
                entry = self.content_registry.get(template_id.strip())
                if parse_stable_key(entry.key).kind == "monster":
                    raise MonsterTemplateReadOnlyError(
                        f"built-in monster template '{template_id}' is read-only and cannot be modified or deleted"
                    )
            except ContentNotFoundError:
                pass
            raise InvalidMonsterTemplateRefError(f"invalid custom template id: '{template_id}'")

    def copy_custom(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        template_id: UUID | str,
        payload: CopyCustomMonsterInput,
    ) -> MonsterLibraryDetailView:
        self._require_room_authority(context, room_id)
        resolved_id = self._resolve_custom_template_id(template_id)

        with self.engine.begin() as connection:
            source = self.repository.get_custom_template(
                room_id, resolved_id, for_update=True, connection=connection
            )
            if source is None:
                raise MonsterTemplateNotFoundError(
                    f"monster template '{resolved_id}' not found in room '{room_id}'"
                )
            if source.revision != payload.expected_revision:
                raise MonsterTemplateRevisionConflictError(
                    f"monster template revision conflict: expected {payload.expected_revision}, got {source.revision}"
                )

            presentation_json = deepcopy(source.presentation_json)
            if payload.name and payload.name.strip():
                name = payload.name.strip()
                names: dict[str, str] = {}
                name_is_custom = True
            else:
                name = f"{source.name} (Copy)"
                names = dict(source.presentation_json.get("names", {})) if isinstance(source.presentation_json.get("names"), dict) else {}
                name_is_custom = True

            rules = deepcopy(source.rules)
            rules["name"] = name

            presentation_json["names"] = names
            presentation_json["name_is_custom"] = name_is_custom

            stored = self.repository.create_custom_template(
                room_id=room_id,
                name=name,
                rules=rules,
                source_key=source.source_key,
                presentation_json=presentation_json,
                connection=connection,
            )
            return self._to_detail_view(stored)

    def patch_custom(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        template_id: UUID | str,
        payload: PatchCustomMonsterInput,
    ) -> MonsterLibraryDetailView:
        self._require_room_authority(context, room_id)
        resolved_id = self._resolve_custom_template_id(template_id)

        with self.engine.begin() as connection:
            source = self.repository.get_custom_template(
                room_id, resolved_id, for_update=True, connection=connection
            )
            if source is None:
                raise MonsterTemplateNotFoundError(
                    f"monster template '{resolved_id}' not found in room '{room_id}'"
                )
            if source.revision != payload.expected_revision:
                raise MonsterTemplateRevisionConflictError(
                    f"monster template revision conflict: expected {payload.expected_revision}, got {source.revision}"
                )

            rules = deepcopy(source.rules)
            presentation_json = deepcopy(source.presentation_json)
            name = source.name

            if "name" in payload.model_fields_set and payload.name is not None:
                name = payload.name.strip()
                rules["name"] = name
                presentation_json["name_is_custom"] = True
                presentation_json["names"] = {}

            if "armor_class" in payload.model_fields_set and payload.armor_class is not None:
                rules["armor_class"] = payload.armor_class
                ac_opts = rules.get("armor_class_options")
                if isinstance(ac_opts, list) and ac_opts and isinstance(ac_opts[0], dict):
                    ac_opts[0]["value"] = payload.armor_class

            if "max_hp" in payload.model_fields_set and payload.max_hp is not None:
                rules["max_hp"] = payload.max_hp

            if "speed" in payload.model_fields_set and payload.speed is not None:
                rules["speed"] = {"walk": payload.speed} if isinstance(payload.speed, str) else payload.speed

            if "size" in payload.model_fields_set and payload.size is not None:
                rules["size"] = payload.size

            if "type" in payload.model_fields_set and payload.type is not None:
                rules["type"] = payload.type

            if "alignment" in payload.model_fields_set and payload.alignment is not None:
                rules["alignment"] = payload.alignment

            if "ability_scores" in payload.model_fields_set and payload.ability_scores is not None:
                if not isinstance(rules.get("ability_scores"), dict):
                    rules["ability_scores"] = {}
                score_dict = rules["ability_scores"]
                if isinstance(score_dict, dict):
                    score_dict.update(payload.ability_scores)

            if "actions" in payload.model_fields_set:
                rules["actions"] = _normalize_actions_collection(payload.actions)

            if "bonus_actions" in payload.model_fields_set:
                rules["bonus_actions"] = _normalize_actions_collection(payload.bonus_actions)

            if "reactions" in payload.model_fields_set:
                rules["reactions"] = _normalize_actions_collection(payload.reactions)

            if "legendary_actions" in payload.model_fields_set:
                rules["legendary_actions"] = _normalize_actions_collection(payload.legendary_actions)

            if "traits" in payload.model_fields_set:
                rules["traits"] = _normalize_traits_collection(payload.traits)

            ability_names = presentation_json.get("ability_names")
            if isinstance(ability_names, dict):
                for group in ("actions", "bonus_actions", "reactions", "legendary_actions", "traits"):
                    if group in payload.model_fields_set:
                        ability_names.pop(group, None)

            if "proficiencies" in payload.model_fields_set and payload.proficiencies is not None:
                rules["proficiencies"] = payload.proficiencies

            if "damage_vulnerabilities" in payload.model_fields_set and payload.damage_vulnerabilities is not None:
                rules["damage_vulnerabilities"] = payload.damage_vulnerabilities

            if "damage_resistances" in payload.model_fields_set and payload.damage_resistances is not None:
                rules["damage_resistances"] = payload.damage_resistances

            if "damage_immunities" in payload.model_fields_set and payload.damage_immunities is not None:
                rules["damage_immunities"] = payload.damage_immunities

            if "condition_immunities" in payload.model_fields_set and payload.condition_immunities is not None:
                rules["condition_immunities"] = payload.condition_immunities

            if "senses" in payload.model_fields_set and payload.senses is not None:
                rules["senses"] = payload.senses

            if "languages" in payload.model_fields_set and payload.languages is not None:
                rules["languages"] = payload.languages

            if "challenge_rating" in payload.model_fields_set and payload.challenge_rating is not None:
                rules["challenge_rating"] = payload.challenge_rating

            if "xp" in payload.model_fields_set and payload.xp is not None:
                rules["xp"] = payload.xp

            if "description" in payload.model_fields_set and payload.description is not None:
                rules["description"] = payload.description

            updated = self.repository.update_custom_template(
                room_id=room_id,
                template_id=resolved_id,
                expected_revision=payload.expected_revision,
                name=name,
                rules=rules,
                presentation_json=presentation_json,
                connection=connection,
            )
            return self._to_detail_view(updated)

    def archive_custom(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        template_id: UUID | str,
        payload: ArchiveCustomMonsterInput,
    ) -> MonsterLibraryDetailView:
        self._require_room_authority(context, room_id)
        resolved_id = self._resolve_custom_template_id(template_id)
        archived = self.repository.archive_custom_template(
            room_id=room_id,
            template_id=resolved_id,
            expected_revision=payload.expected_revision,
        )
        return self._to_detail_view(archived)

    def delete_custom(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        template_id: UUID | str,
        expected_revision: int,
    ) -> None:
        self._require_room_authority(context, room_id)
        resolved_id = self._resolve_custom_template_id(template_id)
        with self.engine.begin() as connection:
            source = self.repository.get_custom_template(
                room_id, resolved_id, for_update=True, connection=connection
            )
            if source is None:
                raise MonsterTemplateNotFoundError(
                    f"monster template '{resolved_id}' not found in room '{room_id}'"
                )
            if source.revision != expected_revision:
                raise MonsterTemplateRevisionConflictError(
                    f"monster template revision conflict: expected {expected_revision}, got {source.revision}"
                )
            if is_monster_template_referenced(connection, room_id=room_id, template_id=resolved_id):
                raise MonsterTemplateReferencedError(
                    f"monster template '{resolved_id}' is referenced and cannot be deleted"
                )
            self.repository.delete_custom_template(
                room_id=room_id,
                template_id=resolved_id,
                expected_revision=expected_revision,
                connection=connection,
            )

    def create_from_instance(
        self,
        context: RoomAccessContext,
        room_id: UUID,
        payload: CreateCustomMonsterFromInstanceInput,
    ) -> MonsterLibraryDetailView:
        self._require_room_authority(context, room_id)
        instance = self.monster_repository.get_instance(payload.instance_id)
        if instance is None:
            raise MonsterTemplateNotFoundError(f"instance '{payload.instance_id}' not found")
        with self.engine.connect() as conn:
            instance_room_id = conn.scalar(
                select(campaigns.c.room_id).where(campaigns.c.id == instance.campaign_id)
            )
        if instance_room_id != room_id:
            raise MonsterTemplateNotFoundError(
                f"instance '{payload.instance_id}' does not belong to room '{room_id}'"
            )
        stored = self.monster_repository.save_instance_as_template(
            payload.instance_id,
            name=payload.name,
        )
        return self._to_detail_view(stored)
