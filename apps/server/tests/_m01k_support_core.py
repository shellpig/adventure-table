"""Shared fixtures for the M01-K PHB feat / spell catalog tests.

The M01-K matrices all need the same three things: a draft whose required
choices are filled in except for the feat opportunity under test, a way to find
a feat's nested child choices, and a real-backend client for the persistence and
restart contracts. Keeping them here avoids six near-identical copies.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.content import load_default_content_registry
from app.domain.character.schemas import StaticDerivedModifier
from app.db import metadata
# The service layer compiles through m01i_compiler, which is what composes the
# M01-I / M01-J / M01-K passes onto the P0/P1 core. Tests must use the same entry
# point or they never reach the K resolver at all.
from app.domain.character_builder.m01i_compiler import compile_builder_draft
from app.domain.character_builder.m01k_feats import _child_choice_id
from app.domain.character_builder.schemas import (
    BuilderBasicInput,
    BuilderChoice,
    BuilderChoiceSelection,
    BuilderDraft,
    BuilderDraftPayload,
    BuilderLevelChoice,
    BuilderMode,
    BuilderReferenceSelection,
    BuilderSpellcastingProfileSummary,
    BuilderSpellChoiceInput,
)
from app.domain.character_builder.service import CharacterBuilderService
from app.main import app
from app.persistence.builder_drafts import BuilderDraftRepository
from app.persistence.characters import CharacterRepository


# Choices the auto-filler must never touch: they are part of the draft skeleton
# each test declares up front, not generic required selections.
DIRECT_SOURCES = {
    "content:race",
    "content:background",
    "content:alignment",
    "content:subrace",
    "content:class",
    "content:subclass",
    "builder:ability-generation",
    "equipment",
}

FEAT_OPPORTUNITY_SOURCES = {"content:race-feat", "content:asi-feat"}

DEFAULT_ABILITIES = {
    "strength": 15,
    "dexterity": 13,
    "constitution": 14,
    "intelligence": 13,
    "wisdom": 12,
    "charisma": 10,
}


def registry():
    return load_default_content_registry()


def draft(payload: BuilderDraftPayload, *, mode: BuilderMode = BuilderMode.CREATE) -> BuilderDraft:
    now = datetime.now(UTC)
    return BuilderDraft(
        id=uuid4(),
        mode=mode,
        revision=1,
        draft_payload=payload,
        created_at=now,
        updated_at=now,
    )


def level(
    character_level: int,
    class_index: str,
    *,
    hp: int,
    subclass_ref: str | None = None,
) -> BuilderLevelChoice:
    return BuilderLevelChoice(
        character_level=character_level,
        class_ref=f"srd5.1:class:{class_index}",
        hp_method="first_level" if character_level == 1 else "fixed_average",
        hp_base_gain=hp,
        subclass_ref=subclass_ref,
    )


def class_levels(
    class_index: str,
    target: int,
    *,
    first_hp: int,
    later_hp: int,
    subclass_ref: str | None = None,
    subclass_level: int = 3,
) -> tuple[BuilderLevelChoice, ...]:
    return tuple(
        level(
            index,
            class_index,
            hp=first_hp if index == 1 else later_hp,
            subclass_ref=subclass_ref if index == subclass_level else None,
        )
        for index in range(1, target + 1)
    )


def payload(
    levels: tuple[BuilderLevelChoice, ...],
    *,
    name: str = "M01-K Hero",
    race: str = "srd5.1:race:human",
    background: str = "srd5.1:background:acolyte",
    abilities: dict[str, int] | None = None,
    selections: dict[str, BuilderChoiceSelection] | None = None,
    numeric_overrides: tuple[dict[str, object], ...] = (),
) -> BuilderDraftPayload:
    return BuilderDraftPayload(
        basic=BuilderBasicInput(name=name),
        target_level=len(levels),
        race_selection=BuilderReferenceSelection(reference_id=race),
        background_selection=BuilderReferenceSelection(reference_id=background),
        ability_generation={
            "method": "manual",
            "scores": dict(abilities or DEFAULT_ABILITIES),
        },
        level_choices=levels,
        choice_selections=dict(selections or {}),
        numeric_overrides=numeric_overrides,
    )


def selection(choice_id: str, *option_ids: str, source_ref: str | None = None) -> BuilderChoiceSelection:
    return BuilderChoiceSelection(
        choice_id=choice_id,
        source_ref=source_ref,
        selected_option_ids=tuple(option_ids),
    )


def with_selections(
    base: BuilderDraftPayload,
    extra: dict[str, BuilderChoiceSelection],
) -> BuilderDraftPayload:
    merged = dict(base.choice_selections)
    merged.update(extra)
    return base.model_copy(update={"choice_selections": merged})


def compile_payload(base: BuilderDraftPayload, content=None):
    content = content or registry()
    return compile_builder_draft(draft(base), content), content


def auto_fill(
    base: BuilderDraftPayload,
    content=None,
    *,
    skip_sources: set[str] | None = None,
    skip_choice_ids: set[str] | None = None,
    rounds: int = 12,
) -> BuilderDraftPayload:
    """Fill every required choice with the first legal option.

    ``skip_sources`` / ``skip_choice_ids`` leave a choice deliberately unresolved
    so a test can drive it by hand. Feat opportunities are skipped by default:
    every M01-K matrix wants to pick the feat itself.
    """

    content = content or registry()
    skip_sources = FEAT_OPPORTUNITY_SOURCES if skip_sources is None else skip_sources
    skip_choice_ids = skip_choice_ids or set()
    selections = dict(base.choice_selections)
    equipment = dict(base.starting_equipment_choices)
    used_refs: set[str] = set()
    for record in selections.values():
        used_refs.update(record.selected_option_ids)

    for _ in range(rounds):
        current = base.model_copy(
            update={
                "choice_selections": selections,
                "starting_equipment_choices": equipment,
            }
        )
        result = compile_builder_draft(draft(current), content)
        changed = False
        for choice in result.choices:
            if choice.option_source == "equipment":
                if choice.choice_id in equipment or choice.disabled_reason is not None:
                    continue
                legal = [item for item in choice.options if item.disabled_reason is None]
                assert len(legal) >= choice.choose_count, choice.choice_id
                equipment[choice.choice_id] = [
                    item.option_id for item in legal[: choice.choose_count]
                ]
                changed = True
                continue
            if (
                not choice.required
                or choice.disabled_reason is not None
                or choice.option_source in DIRECT_SOURCES
                or choice.option_source in skip_sources
                or choice.choice_id in skip_choice_ids
                or choice.choice_id in selections
            ):
                continue
            available = [
                option
                for option in choice.options
                if option.disabled_reason is None
                and (
                    choice.allow_duplicates
                    or option.reference_id is None
                    or option.option_id not in used_refs
                )
            ]
            if choice.allow_duplicates and available:
                picked = tuple(available[0].option_id for _ in range(choice.choose_count))
            else:
                assert len(available) >= choice.choose_count, choice.choice_id
                picked = tuple(option.option_id for option in available[: choice.choose_count])
            used_refs.update(picked)
            selections[choice.choice_id] = BuilderChoiceSelection(
                choice_id=choice.choice_id,
                source_ref=choice.source_ref,
                selected_option_ids=picked,
            )
            changed = True
        if not changed:
            return base.model_copy(
                update={
                    "choice_selections": selections,
                    "starting_equipment_choices": equipment,
                }
            )
    raise AssertionError("required choices did not converge")


def _pick_spells(
    options,
    *,
    count: int,
    cantrips: bool,
    prefer: tuple[str, ...],
    taken: set[str],
) -> tuple[str, ...]:
    pool = [
        option
        for option in options
        if (option.level == 0 if cantrips else option.level >= 1)
        and option.spell_key not in taken
    ]
    ordered = [option for option in pool if option.spell_key in prefer]
    ordered += [option for option in pool if option.spell_key not in prefer]
    picked = tuple(option.spell_key for option in ordered[:count])
    taken.update(picked)
    return picked


def fill_spell_choices(
    base: BuilderDraftPayload,
    content=None,
    *,
    prefer: tuple[str, ...] = (),
) -> BuilderDraftPayload:
    """Satisfy every caster profile's permanent spell selections.

    ``prefer`` pulls named spells to the front of each pool so a test can assert
    that a specific PHB non-SRD spell really made it into the Build.
    """

    content = content or registry()
    result, _ = compile_payload(base, content)
    plan = dict(base.spell_choices)
    for profile in result.resolved_summary.spellcasting_profiles:
        if profile.profile_id in plan:
            continue
        taken: set[str] = set()
        plan[profile.profile_id] = BuilderSpellChoiceInput(
            cantrip_keys=_pick_spells(
                profile.available_spells,
                count=profile.cantrip_count,
                cantrips=True,
                prefer=prefer,
                taken=taken,
            ),
            known_spell_keys=_pick_spells(
                profile.available_spells,
                count=profile.known_spell_count,
                cantrips=False,
                prefer=prefer,
                taken=taken,
            ),
            spellbook_spell_keys=_pick_spells(
                profile.available_spells,
                count=profile.spellbook_count,
                cantrips=False,
                prefer=prefer,
                taken=taken,
            ),
        )
    return base.model_copy(update={"spell_choices": plan})


def spell_profile(result, profile_id: str) -> BuilderSpellcastingProfileSummary:
    matches = [
        profile
        for profile in result.resolved_summary.spellcasting_profiles
        if profile.profile_id == profile_id
    ]
    assert matches, f"missing spellcasting profile {profile_id}"
    return matches[0]


FIGHTER_L4 = ("fighter", 4, 10, 6, "srd5.1:subclass:champion", 3)
WIZARD_L8 = ("wizard", 8, 6, 4, "srd5.1:subclass:evocation", 2)
FIGHTER_L8 = ("fighter", 8, 10, 6, "srd5.1:subclass:champion", 3)


def levels_for(spec) -> tuple[BuilderLevelChoice, ...]:
    class_index, target, first_hp, later_hp, subclass_ref, subclass_level = spec
    return class_levels(
        class_index,
        target,
        first_hp=first_hp,
        later_hp=later_hp,
        subclass_ref=subclass_ref,
        subclass_level=subclass_level,
    )


def feat_draft(
    feat_ref: str,
    *,
    spec=FIGHTER_L4,
    levels: tuple[BuilderLevelChoice, ...] | None = None,
    abilities: dict[str, int] | None = None,
    race: str = "srd5.1:race:human",
    numeric_overrides: tuple[dict[str, object], ...] = (),
    nested: dict[str, tuple[str, ...]] | None = None,
    opportunity_index: int = 0,
    content=None,
    fill_rest: bool = True,
):
    """Build a draft that takes ``feat_ref`` at one feat opportunity.

    Returns ``(result, payload, opportunity_id)``. Nested feat selections are
    addressed by their content field id (``"ability"``, ``"maneuvers"``, ...)
    and resolved through the deterministic child identity.
    """

    content = content or registry()
    base = auto_fill(
        payload(
            levels or levels_for(spec),
            race=race,
            abilities=abilities,
            numeric_overrides=numeric_overrides,
        ),
        content,
    )
    result, _ = compile_payload(base, content)
    opportunity = feat_opportunities(result)[opportunity_index]
    base = with_selections(
        base,
        {opportunity.choice_id: selection(opportunity.choice_id, feat_ref, source_ref=opportunity.source_ref)},
    )
    if nested:
        base = with_selections(base, nested_selections(opportunity.choice_id, feat_ref, nested))
    if fill_rest:
        base = auto_fill(base, content, skip_sources=set())
        base = fill_spell_choices(base, content)
    result, _ = compile_payload(base, content)
    return result, base, opportunity.choice_id


def nested_selections(
    opportunity_id: str,
    feat_ref: str,
    fields: dict[str, tuple[str, ...]],
) -> dict[str, BuilderChoiceSelection]:
    return {
        child_choice_id(opportunity_id, field): selection(
            child_choice_id(opportunity_id, field),
            *values,
            source_ref=feat_ref,
        )
        for field, values in fields.items()
    }


def feat_opportunities(result) -> tuple[BuilderChoice, ...]:
    return tuple(
        choice
        for choice in result.choices
        if choice.option_source in FEAT_OPPORTUNITY_SOURCES
    )


def choice_by_id(result, choice_id: str) -> BuilderChoice:
    matches = [choice for choice in result.choices if choice.choice_id == choice_id]
    assert matches, f"missing choice {choice_id}"
    return matches[-1]


def choice_by_source(result, option_source: str, *, source_ref: str | None = None) -> BuilderChoice:
    matches = [
        choice
        for choice in result.choices
        if choice.option_source == option_source
        and (source_ref is None or choice.source_ref == source_ref)
    ]
    assert matches, f"missing choice for {option_source} / {source_ref}"
    return matches[0]


def child_choice_id(opportunity_id: str, field: str) -> str:
    """Deterministic nested feat choice identity, derived from the opportunity."""

    return _child_choice_id(opportunity_id, field)


def option_by_id(choice: BuilderChoice, option_id: str):
    return next((option for option in choice.options if option.option_id == option_id), None)


def issue_codes(result) -> set[str]:
    return {issue.code for issue in result.validation.issues}


def issues_with_code(result, code: str) -> tuple:
    return tuple(issue for issue in result.validation.issues if issue.code == code)


def feat_entries(content=None):
    content = content or registry()
    return tuple(
        entry for entry in content.list_kind("feat", source="phb2014")
    )


def seed_http(*, raise_server_exceptions: bool = True):
    """Wire the real FastAPI app onto an in-memory database, as P1-F does."""

    content = load_default_content_registry()
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    metadata.create_all(engine)
    character_repository = CharacterRepository(engine, content)
    app.state.content_registry = content
    app.state.character_engine = engine
    app.state.character_repository = character_repository
    app.state.character_builder_service = CharacterBuilderService(
        BuilderDraftRepository(engine),
        content,
        character_repository,
    )
    return TestClient(app, raise_server_exceptions=raise_server_exceptions), engine


def rebind_http(engine) -> TestClient:
    """Rebuild every app-level service against an existing engine.

    This is the restart proxy: the process-level caches (registry, repositories,
    builder service) are rebuilt from scratch while the stored rows stay put.
    """

    content = load_default_content_registry()
    character_repository = CharacterRepository(engine, content)
    app.state.content_registry = content
    app.state.character_engine = engine
    app.state.character_repository = character_repository
    app.state.character_builder_service = CharacterBuilderService(
        BuilderDraftRepository(engine),
        content,
        character_repository,
    )
    return TestClient(app)


def http_create_draft(client: TestClient, draft_payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post(
        "/api/character-builder/drafts",
        json={"draft_payload": draft_payload},
    )
    assert response.status_code == 201, response.text
    return response.json()


def http_patch(
    client: TestClient,
    view: dict[str, Any],
    body: dict[str, Any],
    *,
    expect: int = 200,
) -> dict[str, Any]:
    response = client.patch(
        f"/api/character-builder/drafts/{view['draft']['id']}",
        json={"expected_revision": view["draft"]["revision"], "draft_payload": body},
    )
    assert response.status_code == expect, response.text
    return response.json()


def http_selected_refs(view: dict[str, Any]) -> set[str]:
    selections = view["draft"]["draft_payload"].get("choice_selections") or {}
    choices = {choice["choice_id"]: choice for choice in view["choices"]}
    result: set[str] = set()
    for choice_id, record in selections.items():
        choice = choices.get(choice_id)
        if not choice:
            continue
        options = {option["option_id"]: option for option in choice["options"]}
        for option_id in record.get("selected_option_ids", []):
            option = options.get(option_id)
            if option and option.get("reference_id") and option.get("category") != "ability_bonus":
                result.add(option["reference_id"])
    return result


def http_fill_generic(
    client: TestClient,
    view: dict[str, Any],
    *,
    skip_sources: set[str] | None = None,
) -> dict[str, Any]:
    skip_sources = DIRECT_SOURCES | (skip_sources or set())
    draft_id = view["draft"]["id"]
    for _ in range(14):
        selections = dict(view["draft"]["draft_payload"].get("choice_selections") or {})
        used_refs = http_selected_refs(view)
        changed = False
        for choice in view["choices"]:
            if (
                not choice["required"]
                or choice.get("disabled_reason")
                or choice.get("option_source") in skip_sources
            ):
                continue
            current = selections.get(choice["choice_id"], {}).get("selected_option_ids", [])
            if len(current) == choice["choose_count"]:
                continue
            picked: list[str] = []
            for option in choice["options"]:
                if option.get("disabled_reason"):
                    continue
                reference_id = option.get("reference_id")
                if (
                    reference_id
                    and option.get("category") != "ability_bonus"
                    and reference_id in used_refs
                ):
                    continue
                picked.append(option["option_id"])
                if reference_id and option.get("category") != "ability_bonus":
                    used_refs.add(reference_id)
                if len(picked) == choice["choose_count"]:
                    break
            if len(picked) < choice["choose_count"] and choice.get("allow_duplicates"):
                legal = [item for item in choice["options"] if not item.get("disabled_reason")]
                while legal and len(picked) < choice["choose_count"]:
                    picked.append(legal[0]["option_id"])
            assert len(picked) == choice["choose_count"], choice["label"]
            selections[choice["choice_id"]] = {
                "choice_id": choice["choice_id"],
                "source_ref": choice.get("source_ref"),
                "selected_option_ids": picked,
            }
            changed = True
        if not changed:
            return view
        response = client.patch(
            f"/api/character-builder/drafts/{draft_id}",
            json={
                "expected_revision": view["draft"]["revision"],
                "draft_payload": {"choice_selections": selections},
            },
        )
        assert response.status_code == 200, response.text
        view = response.json()
    raise AssertionError("generic builder choices did not converge")


def http_fill_equipment(client: TestClient, view: dict[str, Any]) -> dict[str, Any]:
    draft_id = view["draft"]["id"]
    for _ in range(12):
        selections = dict(view["draft"]["draft_payload"].get("starting_equipment_choices") or {})
        changed = False
        for choice in view["choices"]:
            if choice.get("option_source") != "equipment" or choice.get("disabled_reason"):
                continue
            current = selections.get(choice["choice_id"]) or []
            if isinstance(current, str):
                current = [current]
            if len(current) == choice["choose_count"]:
                continue
            legal = [item for item in choice["options"] if not item.get("disabled_reason")]
            picked = [item["option_id"] for item in legal[: choice["choose_count"]]]
            assert len(picked) == choice["choose_count"], choice["label"]
            selections[choice["choice_id"]] = picked
            changed = True
        if not changed:
            return view
        response = client.patch(
            f"/api/character-builder/drafts/{draft_id}",
            json={
                "expected_revision": view["draft"]["revision"],
                "draft_payload": {"starting_equipment_choices": selections},
            },
        )
        assert response.status_code == 200, response.text
        view = response.json()
    raise AssertionError("equipment choices did not converge")


def http_confirm(client: TestClient, view: dict[str, Any], *, expect: int = 200) -> dict[str, Any]:
    response = client.post(
        f"/api/character-builder/drafts/{view['draft']['id']}/confirm",
        json={"expected_revision": view["draft"]["revision"]},
    )
    assert response.status_code == expect, response.text
    return response.json()
