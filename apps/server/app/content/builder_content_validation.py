from __future__ import annotations

from collections import defaultdict
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.content.identity import parse_stable_key, reference_to_stable_key, stable_key_is_kind
from app.content.registry import ContentRegistry, ContentValidationError
from app.content.schemas import APIReference, ContentEntry


class _PermissiveModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)


class BuilderChoiceRuleData(_PermissiveModel):
    desc: str | None = None
    choose: int = Field(ge=0)
    type: str
    from_: dict[str, Any] = Field(alias="from")


class BuilderStartingEquipmentData(_PermissiveModel):
    equipment: APIReference
    quantity: int = Field(ge=1)


class BuilderMulticlassPrerequisiteData(_PermissiveModel):
    ability_score: APIReference
    minimum_score: int = Field(ge=1, le=30)


class BuilderMulticlassData(_PermissiveModel):
    prerequisites: list[BuilderMulticlassPrerequisiteData] = Field(default_factory=list)
    prerequisite_options: dict[str, Any] | None = None
    proficiencies: list[APIReference] = Field(default_factory=list)
    proficiency_choices: list[BuilderChoiceRuleData] = Field(default_factory=list)


class BuilderSpellcastingIdentityData(_PermissiveModel):
    level: int = Field(ge=1, le=20)
    spellcasting_ability: APIReference
    ritual_casting: bool | None = None
    focus_requirement: dict[str, Any] | None = None
    info: list[dict[str, Any]] = Field(default_factory=list)


class BuilderClassData(_PermissiveModel):
    index: str
    name: str
    hit_die: int
    proficiency_choices: list[BuilderChoiceRuleData] = Field(default_factory=list)
    proficiencies: list[APIReference] = Field(default_factory=list)
    saving_throws: list[APIReference]
    starting_equipment: list[BuilderStartingEquipmentData] = Field(default_factory=list)
    starting_equipment_options: list[BuilderChoiceRuleData] = Field(default_factory=list)
    multi_classing: BuilderMulticlassData | None = None
    subclasses: list[APIReference]
    spellcasting: BuilderSpellcastingIdentityData | None = None
    spell_list: list[APIReference] = Field(default_factory=list)


def _reference_payload(reference: APIReference) -> dict[str, Any]:
    return reference.model_dump(exclude_none=True, by_alias=True)


def _target_pack_is_installed_but_disabled(registry: ContentRegistry, key: str) -> bool:
    """True only for refs into a pack that ships but is deliberately disabled.

    A source that is not installed at all stays a hard validation failure: that
    is a bad StableKey, not an M03 subset choice.
    """

    source = parse_stable_key(key).source
    return source in registry.installed_pack_ids and source not in registry.enabled_pack_ids


def _validate_spell_relation(
    registry: ContentRegistry,
    owner: ContentEntry,
    references: list[APIReference],
    field: str,
) -> None:
    for reference in references:
        try:
            key = reference_to_stable_key(_reference_payload(reference), kinds={"spell"})
        except ValueError as exc:
            raise ContentValidationError(
                f"{owner.key}.{field} contains an invalid spell reference"
            ) from exc
        if key is None:
            raise ContentValidationError(
                f"{owner.key}.{field} has dangling spell reference: {key}"
            )
        if registry.get_optional(key) is None:
            if _target_pack_is_installed_but_disabled(registry, key):
                continue
            raise ContentValidationError(
                f"{owner.key}.{field} has dangling spell reference: {key}"
            )


def _require_key(
    registry: ContentRegistry,
    *,
    owner: str,
    field: str,
    value: object,
    kind: str,
) -> str:
    if not isinstance(value, str):
        raise ContentValidationError(f"{owner}.{field} must be a {kind} StableKey")
    try:
        valid_kind = stable_key_is_kind(value, kind)
    except ValueError as exc:
        raise ContentValidationError(f"{owner}.{field} has invalid StableKey: {value}") from exc
    if not valid_kind:
        raise ContentValidationError(f"{owner}.{field} has dangling {kind} reference: {value}")
    target = registry.get_optional(value)
    if target is None:
        if _target_pack_is_installed_but_disabled(registry, value):
            return value
        raise ContentValidationError(f"{owner}.{field} has dangling {kind} reference: {value}")
    return value


def _require_feature_refs(
    registry: ContentRegistry,
    *,
    owner: str,
    field: str,
    values: object,
) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list):
        raise ContentValidationError(f"{owner}.{field} must be a list")
    return tuple(
        _require_key(
            registry,
            owner=owner,
            field=f"{field}[{index}]",
            value=value,
            kind="feature",
        )
        for index, value in enumerate(values)
    )


def _require_installed_pool(
    pools: dict[str, list[str]],
    *,
    owner: str,
    field: str,
    value: object,
) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ContentValidationError(f"{owner}.{field} must be a non-empty pool id")
    if not pools.get(value):
        raise ContentValidationError(f"{owner}.{field} references an empty or unknown pool: {value}")
    return value


def _validate_m01i_feature_relations(registry: ContentRegistry) -> None:
    """Fail fast on the string-key relations introduced by M01-I.

    These relations intentionally live in permissive ContentEntry.data so the
    generic content schema is not turned into a D&D rules DSL. Because they are
    StableKey strings rather than APIReference objects, the generic registry
    cross-reference walker cannot validate them; M01-I owns that boundary here.
    """

    feature_indices: dict[str, list[str]] = defaultdict(list)
    spell_indices: dict[str, list[str]] = defaultdict(list)
    pools: dict[str, list[str]] = defaultdict(list)
    for entry in registry.list_kind("feature"):
        feature_indices[entry.index].append(entry.key)
        option = entry.data.get("choice_pool_option")
        if isinstance(option, dict):
            pool = option.get("pool")
            if isinstance(pool, str) and pool:
                pools[pool].append(entry.key)
    for entry in registry.list_kind("spell"):
        spell_indices[entry.index].append(entry.key)

    for entry in registry.list_kind("feature", source="tce"):
        root = entry.data.get("optional_class_feature")
        if isinstance(root, dict):
            parent = _require_key(
                registry,
                owner=entry.key,
                field="optional_class_feature.parent_class_ref",
                value=root.get("parent_class_ref"),
                kind="class",
            )
            spell_access = root.get("spell_access")
            if spell_access is not None:
                if not isinstance(spell_access, dict):
                    raise ContentValidationError(
                        f"{entry.key}.optional_class_feature.spell_access must be an object"
                    )
                spell_class = _require_key(
                    registry,
                    owner=entry.key,
                    field="optional_class_feature.spell_access.class_ref",
                    value=spell_access.get("class_ref"),
                    kind="class",
                )
                if spell_class != parent:
                    raise ContentValidationError(
                        f"{entry.key}: expanded spell access class must match parent class"
                    )
                for index, spell_ref in enumerate(spell_access.get("spell_refs", [])):
                    _require_key(
                        registry,
                        owner=entry.key,
                        field=f"optional_class_feature.spell_access.spell_refs[{index}]",
                        value=spell_ref,
                        kind="spell",
                    )
                raw_indices = spell_access.get("spell_indices", [])
                if not isinstance(raw_indices, list):
                    raise ContentValidationError(
                        f"{entry.key}.optional_class_feature.spell_access.spell_indices must be a list"
                    )
                for spell_index in raw_indices:
                    if not isinstance(spell_index, str) or not spell_index:
                        raise ContentValidationError(
                            f"{entry.key}: expanded spell index must be non-empty text"
                        )
                    matches = spell_indices.get(spell_index, [])
                    if not matches:
                        raise ContentValidationError(
                            f"{entry.key}: expanded spell index is not installed: {spell_index}"
                        )
                    if len(matches) > 1:
                        raise ContentValidationError(
                            f"{entry.key}: expanded spell index is ambiguous: {spell_index} -> {matches}"
                        )

            extensions = root.get("pool_extensions", [])
            if not isinstance(extensions, list):
                raise ContentValidationError(
                    f"{entry.key}.optional_class_feature.pool_extensions must be a list"
                )
            for ext_index, extension in enumerate(extensions):
                if not isinstance(extension, dict):
                    raise ContentValidationError(
                        f"{entry.key}.optional_class_feature.pool_extensions[{ext_index}] must be an object"
                    )
                _require_feature_refs(
                    registry,
                    owner=entry.key,
                    field=f"optional_class_feature.pool_extensions[{ext_index}].option_refs",
                    values=extension.get("option_refs", []),
                )
                option_pool = extension.get("option_pool")
                if option_pool is not None:
                    _require_installed_pool(
                        pools,
                        owner=entry.key,
                        field=f"optional_class_feature.pool_extensions[{ext_index}].option_pool",
                        value=option_pool,
                    )
                targets = extension.get("target_feature_indices", [])
                if not isinstance(targets, list):
                    raise ContentValidationError(
                        f"{entry.key}: target_feature_indices must be a list"
                    )
                if extension.get("target_required") is True and targets:
                    if not any(feature_indices.get(index) for index in targets if isinstance(index, str)):
                        raise ContentValidationError(
                            f"{entry.key}: required expanded-choice target is not installed"
                        )

            retraining = root.get("retraining")
            if retraining is not None:
                if not isinstance(retraining, dict):
                    raise ContentValidationError(
                        f"{entry.key}.optional_class_feature.retraining must be an object"
                    )
                strategies = retraining.get("strategies", [])
                if not isinstance(strategies, list):
                    raise ContentValidationError(
                        f"{entry.key}.optional_class_feature.retraining.strategies must be a list"
                    )
                for strategy_index, strategy in enumerate(strategies):
                    if not isinstance(strategy, dict):
                        raise ContentValidationError(
                            f"{entry.key}: retraining strategy must be an object"
                        )
                    class_ref = strategy.get("class_ref")
                    if class_ref is not None:
                        _require_key(
                            registry,
                            owner=entry.key,
                            field=(
                                "optional_class_feature.retraining.strategies"
                                f"[{strategy_index}].class_ref"
                            ),
                            value=class_ref,
                            kind="class",
                        )
                    pool = strategy.get("pool")
                    if pool is not None:
                        _require_installed_pool(
                            pools,
                            owner=entry.key,
                            field=(
                                "optional_class_feature.retraining.strategies"
                                f"[{strategy_index}].pool"
                            ),
                            value=pool,
                        )
                    targets = strategy.get("target_feature_indices", [])
                    if not isinstance(targets, list):
                        raise ContentValidationError(
                            f"{entry.key}: retraining target_feature_indices must be a list"
                        )
                    if targets and not any(
                        feature_indices.get(index) for index in targets if isinstance(index, str)
                    ):
                        raise ContentValidationError(
                            f"{entry.key}: retraining target feature is not installed"
                        )

        option = entry.data.get("choice_pool_option")
        if not isinstance(option, dict):
            continue
        eligible = option.get("eligible_class_refs", [])
        if not isinstance(eligible, list):
            raise ContentValidationError(f"{entry.key}.choice_pool_option.eligible_class_refs must be a list")
        for class_index, class_ref in enumerate(eligible):
            _require_key(
                registry,
                owner=entry.key,
                field=f"choice_pool_option.eligible_class_refs[{class_index}]",
                value=class_ref,
                kind="class",
            )
        _require_feature_refs(
            registry,
            owner=entry.key,
            field="choice_pool_option.required_feature_refs",
            values=option.get("required_feature_refs", []),
        )
        _require_feature_refs(
            registry,
            owner=entry.key,
            field="choice_pool_option.any_required_feature_refs",
            values=option.get("any_required_feature_refs", []),
        )
        nested = option.get("nested")
        if isinstance(nested, dict):
            if nested.get("class_ref") is not None:
                _require_key(
                    registry,
                    owner=entry.key,
                    field="choice_pool_option.nested.class_ref",
                    value=nested.get("class_ref"),
                    kind="class",
                )
            pool = nested.get("pool")
            if pool is not None:
                _require_installed_pool(
                    pools,
                    owner=entry.key,
                    field="choice_pool_option.nested.pool",
                    value=pool,
                )
            targets = nested.get("target_feature_indices", [])
            if not isinstance(targets, list):
                raise ContentValidationError(
                    f"{entry.key}.choice_pool_option.nested.target_feature_indices must be a list"
                )
            if targets and not any(
                feature_indices.get(index) for index in targets if isinstance(index, str)
            ):
                raise ContentValidationError(
                    f"{entry.key}: nested target feature is not installed"
                )


def validate_builder_content(registry: ContentRegistry) -> ContentRegistry:
    """Validate Builder-only fields and cross-pack relations."""

    for class_entry in registry.list_kind("class", source="tce"):
        try:
            parsed = BuilderClassData.model_validate(class_entry.data)
        except ValidationError as exc:
            raise ContentValidationError(
                f"invalid Character Builder class data for {class_entry.key}: {exc}"
            ) from exc
        _validate_spell_relation(registry, class_entry, parsed.spell_list, "spell_list")

    for subclass_entry in registry.list_kind("subclass", source="tce"):
        raw_spells = subclass_entry.data.get("spells")
        if raw_spells is None:
            continue
        if not isinstance(raw_spells, list):
            raise ContentValidationError(f"{subclass_entry.key}.spells must be a list")
        references: list[APIReference] = []
        for index, row in enumerate(raw_spells):
            if not isinstance(row, dict) or not isinstance(row.get("spell"), dict):
                raise ContentValidationError(
                    f"{subclass_entry.key}.spells[{index}] is missing a spell reference"
                )
            try:
                references.append(APIReference.model_validate(row["spell"]))
            except ValidationError as exc:
                raise ContentValidationError(
                    f"{subclass_entry.key}.spells[{index}] has invalid spell identity"
                ) from exc
        _validate_spell_relation(registry, subclass_entry, references, "spells")

    _validate_m01i_feature_relations(registry)
    return registry
