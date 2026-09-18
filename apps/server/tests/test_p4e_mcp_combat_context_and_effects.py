from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import MagicMock
from uuid import UUID, uuid4

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import insert, select, update

from app.api.dependencies import get_content_registry, get_database_engine
from app.api.rooms.access import get_room_service
from app.api.rooms.ai_controllers import get_ai_controller_service
from app.api.rooms.dependencies import (
    get_combat_adjudication_service,
    get_combat_attack_service,
    get_combat_concentration_service,
    get_combat_core_roll_service,
    get_combat_initiative_service,
    get_combat_reaction_service,
    get_combat_resolution_service,
    get_combat_service,
    get_combat_special_attack_service,
    get_combat_spell_service,
    get_monster_instance_service,
    get_table_event_service,
)
from app.content import load_default_content_registry
from app.domain.character.schemas import (
    CharacterBuild,
    CharacterState,
    ResourceCounter,
    SpellAccessEntry,
    SpellResourcePool,
    SpellSlotCapacity,
    SpellcastingProfile,
)
from app.domain.combat.adjudication_service import CombatAdjudicationService
from app.domain.combat.ai_tools import CombatAIToolApplicationService
from app.domain.combat.attack_definitions import AttackDefinitionResolver
from app.domain.combat.attacks import CombatAttackService
from app.domain.combat.concentration import CombatConcentrationService
from app.domain.combat.core_rolls import CombatCoreRollService
from app.domain.combat.initiative import FinalizeInitiativeInput, RequestInitiativeInput
from app.domain.combat.lifecycle import AddMonsterInput, StartCombatInput
from app.domain.combat.monster_instances import MonsterInstanceService
from app.domain.combat.roll_compat import CombatAwareRollRepository
from app.domain.combat.reaction_service import CombatReactionService
from app.domain.combat.resolution import DamageRollPart, DamageType
from app.domain.combat.semantic_hp import CombatResolutionService
from app.domain.combat.special_attacks import CombatSpecialAttackService
from app.domain.combat.spell_service import CombatSpellService
from app.domain.rooms.ai_controller_tokens import mint_ai_controller_token
from app.domain.rooms.ai_controllers import (
    AIControllerAuthView,
    AIControllerService,
    AIHandoffRequest,
)
from app.domain.rooms.character_rolls import CharacterRollModifierResolver
from app.domain.rooms.exploration import ExplorationStageService
from app.domain.rooms.pending_actions import PendingActionService
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource, RollService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.domain.rooms.service import RoomService
from app.main import app
from app.mcp.dependencies import get_ai_tool_application_service
from app.mcp.protocol import MCP_PROTOCOL_VERSION
from app.mcp.tools import tool_catalog
from app.persistence.characters import character_states, character_versions, characters
from app.persistence.combat.adjudication import CombatAdjudicationRepository
from app.persistence.combat.attacks import CombatAttackRepository
from app.persistence.combat.concentration import CombatConcentrationRepository
from app.persistence.combat.core_rolls import CombatCoreRollRepository
from app.persistence.combat.reactions import CombatReactionRepository
from app.persistence.combat.resolution import CombatResolutionRepository
from app.persistence.combat.special_attacks import SpecialAttackRepository
from app.persistence.combat.spells import CombatSpellRepository
from app.persistence.combat.tables import combat_entries, monster_instances
from app.persistence.rooms.ai_controllers import AIControllerGrantRepository
from app.persistence.rooms.exploration import ExplorationRepository
from app.persistence.rooms.exploration_subjects import ExplorationSubjectRepository
from app.persistence.rooms.p3c_pending import PendingActionRepository
from app.persistence.rooms.p3c_rolls import RollRepository
from app.persistence.rooms.p3c_runtime import roll_requests
from app.persistence.rooms.repository import RoomRepository
from app.persistence.rooms.tables import (
    ai_controller_grants,
    campaign_seats,
    sessions,
)
import tests.test_p4b_combat_lifecycle as support
from tests.test_p4d_persistence import _set_concentration


def _auth(role: str, active: bool = True) -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=uuid4(),
        room_id=uuid4(),
        campaign_id=uuid4(),
        seat_id=uuid4(),
        role=role,
        session_id=uuid4() if active else None,
        generation=1,
        is_current_dm=role == "dm" and active,
        temporary_instruction=None,
    )


def _body(method: str, *, params: dict | None = None, request_id: int | str = 1) -> dict:
    merged = dict(params or {})
    merged["_meta"] = {
        "io.modelcontextprotocol/protocolVersion": MCP_PROTOCOL_VERSION,
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "p4e-test", "version": "1"},
    }
    return {"jsonrpc": "2.0", "id": request_id, "method": method, "params": merged}


def _headers(method: str, *, name: str | None = None, token: str = "fake-token") -> dict[str, str]:
    result = {
        "Authorization": f"Bearer {token}",
        "MCP-Protocol-Version": MCP_PROTOCOL_VERSION,
        "Mcp-Method": method,
    }
    if name is not None:
        result["Mcp-Name"] = name
    return result


def _mcp_call(client: TestClient, token: str, name: str, arguments: dict) -> dict:
    resp = client.post(
        "/mcp",
        json=_body("tools/call", params={"name": name, "arguments": arguments}),
        headers=_headers("tools/call", name=name, token=token),
    )
    assert resp.status_code == 200
    return resp.json()["result"]


def _enable_wizard_spells(table) -> None:
    with table.engine.begin() as connection:
        version_id = connection.scalar(
            select(characters.c.current_version_id).where(
                characters.c.id == table.character_id
            )
        )
        build_row = connection.execute(
            select(character_versions.c.build_payload).where(
                character_versions.c.id == version_id
            )
        ).mappings().one()
        build = CharacterBuild.model_validate(build_row["build_payload"])
        profile = SpellcastingProfile(
            profile_id="wizard",
            source_type="class",
            source_key="srd5.1:class:wizard",
            class_ref="srd5.1:class:wizard",
            ability="intelligence",
            access_model="spellbook",
            resource_pool_type="normal_multiclass_slots",
            max_spell_level=3,
            prepared_limit=8,
        )
        pool = SpellResourcePool(
            pool_id="normal_multiclass",
            pool_type="normal_multiclass_slots",
            slots=(
                SpellSlotCapacity(level=1, capacity=4),
                SpellSlotCapacity(level=2, capacity=3),
                SpellSlotCapacity(level=3, capacity=2),
            ),
        )
        hold_person_access = SpellAccessEntry(
            entry_id="wizard:hold-person",
            spell_key="srd5.1:spell:hold-person",
            source_type="class",
            source_key="srd5.1:class:wizard",
            access_type="spellbook",
        )
        existing_entry_ids = {item.entry_id for item in build.spell_access_entries}
        new_entries = [
            item for item in (hold_person_access,)
            if item.entry_id not in existing_entry_ids
        ]
        next_build = build.model_copy(
            update={
                "spellcasting_profiles": (profile,),
                "spell_resource_pools": (pool,),
                "spell_access_entries": (
                    *build.spell_access_entries,
                    *new_entries,
                ),
            },
            deep=True,
        )
        connection.execute(
            update(character_versions)
            .where(character_versions.c.id == version_id)
            .values(build_payload=next_build.model_dump(mode="json"))
        )
        state_row = connection.execute(
            select(character_states.c.state_payload, character_states.c.state_revision).where(
                character_states.c.character_id == table.character_id
            )
        ).mappings().one()
        state = CharacterState.model_validate(state_row["state_payload"])
        prepared = list(state.prepared_spell_entry_ids)
        if "wizard:hold-person" not in prepared:
            prepared.append("wizard:hold-person")
        next_state = state.model_copy(
            update={
                "prepared_spell_entry_ids": prepared,
                "spell_slots": {
                    1: ResourceCounter(used=0, remaining=4),
                    2: ResourceCounter(used=0, remaining=3),
                    3: ResourceCounter(used=0, remaining=2),
                },
            },
            deep=True,
        )
        connection.execute(
            update(character_states)
            .where(character_states.c.character_id == table.character_id)
            .values(
                state_payload=next_state.model_dump(mode="json"),
                state_revision=int(state_row["state_revision"]) + 1,
            )
        )


@pytest.fixture
def mcp_combat_fixture():
    table = support._setup()
    try:
        _enable_wizard_spells(table)

        # Start combat
        table.combat.start_quick_combat(
            table.dm_actor,
            StartCombatInput(idempotency_key="mcp-combat-test-start"),
        )

        # Set character HP
        char = table.combat.character_repository.load_character(table.character_id)
        char.state.current_hp = 20
        char.state.temporary_hp = 5
        table.combat.character_repository.save_state(table.character_id, char.state)

        # Hostile monster
        evil_mage = table.monsters.create_instance(
            campaign_id=table.campaign_id,
            name="Evil Mage",
            rules_snapshot={
                "armor_class": 15,
                "max_hp": 44,
                "speed": {"walk": 30},
                "description": "A sinister spellcaster.",
            },
            current_hp=19,
            temp_hp=4,
            resources={"spell_slot:1": 2},
            conditions=["prone", {"name": "secret-mark", "visibility": "hidden"}],
            position_note="behind pillar",
        )
        with table.engine.begin() as conn:
            conn.execute(
                update(monster_instances)
                .where(monster_instances.c.id == evil_mage.id)
                .values(
                    concentration={"source_ref": "srd5.1:spell:fly", "effect_ids": ["eff-fly"]}
                )
            )

        table.combat.add_monster(
            table.dm_actor,
            AddMonsterInput(
                monster_instance_id=evil_mage.id,
                idempotency_key="mcp-add-evil-mage",
            ),
        )

        requested = table.initiative.request_initiative(
            table.dm_actor,
            RequestInitiativeInput(idempotency_key="mcp-combat-init"),
        )
        for index, req in enumerate(requested.requests):
            actor = table.player_actor if req.target_seat_id is not None else table.dm_actor
            raw = 20 if req.target_seat_id is not None else 1
            table.initiative.complete_initiative(
                actor,
                FormalRollInput(
                    roll_request_id=req.id,
                    source=FormalRollSource.PHYSICAL,
                    raw_dice=(raw,),
                    idempotency_key=f"mcp-init-roll-{index}",
                ),
            )

        with table.engine.connect() as connection:
            rows = connection.execute(
                select(
                    combat_entries.c.id,
                    combat_entries.c.character_id,
                    combat_entries.c.monster_instance_id,
                ).where(
                    combat_entries.c.combat_id
                    == table.combat.get_active_combat(table.dm_actor).id
                )
            ).mappings().all()
        mage_entry = next(r for r in rows if r["monster_instance_id"] == evil_mage.id)
        char_entry = next(r for r in rows if r["character_id"] == table.character_id)

        # Character first in turn order
        table.initiative.finalize_initiative(
            table.dm_actor,
            FinalizeInitiativeInput(
                ordered_entry_ids=(char_entry["id"], mage_entry["id"]),
                idempotency_key="mcp-finalize-init",
            ),
        )

        registry = load_default_content_registry()
        room_service = RoomService(RoomRepository(table.engine))
        monster_service = MonsterInstanceService(
            monster_repository=table.monsters,
            content_registry=registry,
            table_event_service=table.events,
        )
        grant_repo = AIControllerGrantRepository(table.engine)
        ai_controller_service = AIControllerService(grant_repo, table.events)

        spell_repo = CombatSpellRepository(table.engine, table.events.repository)
        reaction_repo = CombatReactionRepository(table.engine, table.events.repository)
        conc_repo = CombatConcentrationRepository(table.engine, table.events.repository)
        adj_repo = CombatAdjudicationRepository(table.engine, table.events.repository)
        attack_repo = CombatAttackRepository(table.engine, table.events.repository)
        res_repo = CombatResolutionRepository(table.engine, table.events.repository)
        core_repo = CombatCoreRollRepository(table.engine, table.events.repository)
        spec_repo = SpecialAttackRepository(table.engine, table.events.repository)

        plain_roll_repo = CombatAwareRollRepository(table.engine, table.events.repository)
        roll_service = RollService(
            repository=plain_roll_repo,
            subject_repository=ExplorationSubjectRepository(table.engine),
            table_event_service=table.events,
            modifier_resolver=CharacterRollModifierResolver(
                table.combat.character_repository, registry
            ),
            registry=registry,
        )

        spell_service = CombatSpellService(
            repository=spell_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            table_event_service=table.events,
            monster_repository=table.monsters,
            character_repository=table.combat.character_repository,
            roll_service=roll_service,
            registry=registry,
        )
        reaction_service = CombatReactionService(
            repository=reaction_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            table_event_service=table.events,
        )
        conc_service = CombatConcentrationService(
            repository=conc_repo,
            combat_repository=table.combat.repository,
            monster_repository=table.monsters,
            roll_service=roll_service,
            table_event_service=table.events,
        )
        adj_service = CombatAdjudicationService(
            repository=adj_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            table_event_service=table.events,
        )
        attack_service = CombatAttackService(
            repository=attack_repo,
            adjudication_repository=adj_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            definition_resolver=AttackDefinitionResolver(
                character_repository=table.combat.character_repository,
                monster_repository=table.monsters,
                registry=registry,
            ),
            roll_service=roll_service,
            table_event_service=table.events,
        )
        resolution_service = CombatResolutionService(
            repository=res_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            table_event_service=table.events,
        )
        core_roll_service = CombatCoreRollService(
            repository=core_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            monster_repository=table.monsters,
            roll_service=roll_service,
            table_event_service=table.events,
            concentration_service=conc_service,
        )
        special_attack_service = CombatSpecialAttackService(
            repository=spec_repo,
            core_roll_repository=core_repo,
            combat_repository=table.combat.repository,
            combat_service=table.combat,
            character_repository=table.combat.character_repository,
            monster_repository=table.monsters,
            registry=registry,
            roll_service=roll_service,
            table_event_service=table.events,
        )

        combat_ai_tool_service = CombatAIToolApplicationService(
            ai_controller_service=ai_controller_service,
            session_service=table.session_service,
            stage_service=ExplorationStageService(ExplorationRepository(table.engine), table.events),
            action_service=object(),
            roll_service=roll_service,
            state_service=object(),
            pending_action_service=PendingActionService(
                PendingActionRepository(table.engine, table.events.repository),
                ExplorationSubjectRepository(table.engine),
                table.events,
                plain_roll_repo,
            ),
            event_service=table.events,
            workspace_service=object(),
            combat_service=table.combat,
            combat_attack_service=attack_service,
            combat_resolution_service=resolution_service,
            combat_core_roll_service=core_roll_service,
            combat_special_attack_service=special_attack_service,
            combat_initiative_service=table.initiative,
            monster_instance_service=monster_service,
            combat_spell_service=spell_service,
            combat_concentration_service=conc_service,
            combat_reaction_service=reaction_service,
            combat_adjudication_service=adj_service,
        )

        app.state.ai_tool_application_service = combat_ai_tool_service
        app.dependency_overrides[get_database_engine] = lambda: table.engine
        app.dependency_overrides[get_content_registry] = lambda: registry
        app.dependency_overrides[get_room_service] = lambda: room_service
        app.dependency_overrides[get_combat_service] = lambda: table.combat
        app.dependency_overrides[get_combat_initiative_service] = lambda: table.initiative
        app.dependency_overrides[get_monster_instance_service] = lambda: monster_service
        app.dependency_overrides[get_table_event_service] = lambda: table.events
        app.dependency_overrides[get_ai_controller_service] = lambda: ai_controller_service
        app.dependency_overrides[get_combat_spell_service] = lambda: spell_service
        app.dependency_overrides[get_combat_concentration_service] = lambda: conc_service
        app.dependency_overrides[get_combat_reaction_service] = lambda: reaction_service
        app.dependency_overrides[get_combat_adjudication_service] = lambda: adj_service
        app.dependency_overrides[get_combat_attack_service] = lambda: attack_service
        app.dependency_overrides[get_combat_resolution_service] = lambda: resolution_service
        app.dependency_overrides[get_combat_core_roll_service] = lambda: core_roll_service
        app.dependency_overrides[get_combat_special_attack_service] = lambda: special_attack_service
        app.dependency_overrides[get_ai_tool_application_service] = lambda: combat_ai_tool_service

        # Player hands off to AI controller
        player_grant = ai_controller_service.let_ai_control_player(
            room_id=table.room_id,
            campaign_id=table.campaign_id,
            session_id=table.session_id,
            seat_id=table.player_seat_id,
            context=RoomAccessContext(
                room_id=table.room_id,
                access_session_id=table.player_actor.access_session_id,
                authority=RoomAccessAuthority.MEMBER,
            ),
            request=AIHandoffRequest(),
        )
        player_token = player_grant.token

        # Mint active AI DM grant
        dm_seat_id = table.dm_actor.seat_id
        minted = mint_ai_controller_token()
        now = datetime.now(timezone.utc)
        with table.engine.begin() as connection:
            connection.execute(
                insert(ai_controller_grants).values(
                    id=minted.grant_id,
                    room_id=table.room_id,
                    campaign_id=table.campaign_id,
                    seat_id=dm_seat_id,
                    role="dm",
                    session_id=table.session_id,
                    secret_hash=minted.secret_hash,
                    secret_prefix=minted.display_hint,
                    generation=1,
                    status="active",
                    pre_session_expires_at=None,
                    handoff_return_access_session_id=None,
                    temporary_instruction=None,
                    created_at=now,
                    bound_at=now,
                    revoked_at=None,
                    last_seen_at=None,
                )
            )
            connection.execute(
                update(campaign_seats)
                .where(campaign_seats.c.id == dm_seat_id)
                .values(
                    controller_kind="ai",
                    ai_controller_grant_id=minted.grant_id,
                    controller_epoch=1,
                    controller_access_session_id=None,
                    updated_at=now,
                )
            )
            connection.execute(
                update(sessions)
                .where(sessions.c.id == table.session_id)
                .values(
                    dm_controller_kind="ai",
                    dm_controller_ai_grant_id=minted.grant_id,
                    dm_controller_generation=1,
                    dm_controller_access_session_id=None,
                )
            )
        dm_token = minted.plaintext

        yield (
            table,
            char_entry["id"],
            mage_entry["id"],
            evil_mage,
            dm_token,
            player_token,
            combat_ai_tool_service,
            adj_service,
            res_repo,
        )
    finally:
        app.dependency_overrides.clear()
        table.engine.dispose()


def test_1_catalog_role_sets_and_pre_session_parity() -> None:
    dm_catalog = {item["name"] for item in tool_catalog(_auth("dm", True))}
    player_catalog = {item["name"] for item in tool_catalog(_auth("player", True))}
    pre_session_dm = {item["name"] for item in tool_catalog(_auth("dm", False))}

    all_11_new = {
        "get_combat_context",
        "combat_cast_spell",
        "combat_propose_aoe_spell",
        "combat_resolve_aoe_spell",
        "combat_roll_concentration",
        "combat_drop_concentration",
        "combat_open_reaction_window",
        "combat_respond_to_reaction",
        "combat_request_opportunity_attack",
        "combat_request_adjudication",
        "combat_resolve_adjudication",
    }
    shared_8 = {
        "get_combat_context",
        "combat_cast_spell",
        "combat_propose_aoe_spell",
        "combat_roll_concentration",
        "combat_drop_concentration",
        "combat_respond_to_reaction",
        "combat_request_opportunity_attack",
        "combat_request_adjudication",
    }
    dm_only_3 = {
        "combat_resolve_aoe_spell",
        "combat_open_reaction_window",
        "combat_resolve_adjudication",
    }

    assert all_11_new <= dm_catalog
    assert shared_8 <= player_catalog
    assert not (dm_only_3 & player_catalog)
    assert pre_session_dm == dm_catalog


def test_2_player_get_combat_context_secrecy(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        facade,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)
    resp = _mcp_call(client, player_token, "get_combat_context", {})
    assert resp["isError"] is False

    structured = resp["structuredContent"]
    data = structured["data"]

    # Verify top-level compact combat context shape
    assert "combat" in data
    assert "current_turn_entry_id" in data
    assert "round" in data
    assert "my_entry_ids" in data
    assert "pending_roll_requests" in data
    assert "reaction_windows" in data
    assert "pending_adjudications" in data
    assert "next_required_action" in data

    # Player controls their character entry
    assert str(char_entry_id) in data["my_entry_ids"]
    assert str(mage_entry_id) not in data["my_entry_ids"]

    combatants = data["combat"]["combatants"]
    monster_cb = next(c for c in combatants if c["subject_kind"] == "monster")
    char_cb = next(c for c in combatants if c["subject_kind"] == "character")

    # Hostile monster projection has NO forbidden secret keys
    monster_proj = monster_cb["projection"]
    forbidden_keys = [
        "current_hp",
        "max_hp",
        "temp_hp",
        "armor_class",
        "resources",
        "hidden_conditions",
        "dm_notes",
        "concentration",
    ]
    for key in forbidden_keys:
        assert key not in monster_proj, f"Forbidden key '{key}' leaked into player monster projection: {monster_proj}"

    # Player character entry has exact HP
    char_proj = char_cb["projection"]
    assert char_proj["current_hp"] == 20
    assert char_proj["temp_hp"] == 5

    # Pending adjudications carry dm_hints == None
    for adj in data["pending_adjudications"]:
        assert adj["dm_hints"] is None

    # rules_snapshot nowhere in the serialized JSON text
    raw_text = resp["content"][0]["text"]
    assert "rules_snapshot" not in raw_text

    # reaction_windows has no secret_payload
    for window in data["reaction_windows"]:
        assert "secret_payload" not in window


def test_3_dm_get_combat_context_and_adjudication_lifecycle(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        facade,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)

    # 1. DM sees exact monster HP and AC
    dm_resp = _mcp_call(client, dm_token, "get_combat_context", {})
    assert dm_resp["isError"] is False
    dm_data = dm_resp["structuredContent"]["data"]
    monster_cb = next(c for c in dm_data["combat"]["combatants"] if c["subject_kind"] == "monster")
    assert monster_cb["projection"]["current_hp"] == 19
    assert monster_cb["projection"]["armor_class"] == 15

    # 2. Player declares attack needing range adjudication -> creates pending adjudication
    attacks_res = _mcp_call(
        client,
        player_token,
        "combat_list_attacks",
        {"entry_id": str(char_entry_id)},
    )
    assert attacks_res["isError"] is False
    source_ref = attacks_res["structuredContent"]["data"]["attacks"][0]["source_ref"]

    attack_res = _mcp_call(
        client,
        player_token,
        "combat_request_attack",
        {
            "attacker_entry_id": str(char_entry_id),
            "target_entry_id": str(mage_entry_id),
            "source_ref": source_ref,
            "range_confirmed": True,
            "idempotency_key": "test-3-attack-req",
        },
    )
    assert attack_res["isError"] is False
    action_id = attack_res["structuredContent"]["data"]["action_id"]

    # DM calls get_combat_context -> sees pending adjudication and next_required_action == "adjudicate_attack"
    dm_resp2 = _mcp_call(client, dm_token, "get_combat_context", {})
    assert dm_resp2["isError"] is False
    dm_data2 = dm_resp2["structuredContent"]["data"]
    assert len(dm_data2["pending_adjudications"]) >= 1
    assert dm_data2["next_required_action"] == "adjudicate_attack"

    # DM resolves range adjudication via combat_adjudicate_attack
    resolve_res = _mcp_call(
        client,
        dm_token,
        "combat_adjudicate_attack",
        {
            "action_id": str(action_id),
            "in_range": True,
            "roll_mode": "normal",
            "note": "Goblin in range",
            "idempotency_key": "test-3-adjudicate-1",
        },
    )
    assert resolve_res["isError"] is False

    # DM calls get_combat_context again -> next_required_action is no longer resolve_adjudication
    dm_resp3 = _mcp_call(client, dm_token, "get_combat_context", {})
    assert dm_resp3["isError"] is False
    dm_data3 = dm_resp3["structuredContent"]["data"]
    assert dm_data3["next_required_action"] in ("take_turn", "wait_for_event")


def test_4_player_concentration_roll_and_routing(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        facade,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)

    # Set up character concentration
    _set_concentration(table)

    # Deal damage to character to trigger concentration CON save RollRequest
    damage_res = _mcp_call(
        client,
        dm_token,
        "combat_apply_damage",
        {
            "target_entry_id": str(char_entry_id),
            "amount": 60,
            "damage_type": "force",
            "idempotency_key": "conc-damage-setup-1",
        },
    )
    assert damage_res["isError"] is False
    check = damage_res["structuredContent"]["data"]["payload"]["concentration_check"]
    req_id = UUID(check["roll_request_id"])

    # Player calls get_combat_context -> next_required_action == "roll_pending"
    p_resp = _mcp_call(client, player_token, "get_combat_context", {})
    p_data = p_resp["structuredContent"]["data"]
    assert p_data["next_required_action"] == "roll_pending"
    pending_ids = [r["id"] for r in p_data["pending_roll_requests"]]
    assert str(req_id) in pending_ids
    player_row = next(r for r in p_data["pending_roll_requests"] if r["id"] == str(req_id))
    assert player_row["label"] == "Concentration"
    assert player_row["dc"] is None  # monster save DCs stay DM-only
    dm_rows = _mcp_call(client, dm_token, "get_combat_context", {})["structuredContent"]["data"]["pending_roll_requests"]
    assert next(r for r in dm_rows if r["id"] == str(req_id))["dc"] is not None

    # Player resolves Concentration save via combat_roll_concentration
    roll_res = _mcp_call(
        client,
        player_token,
        "combat_roll_concentration",
        {
            "roll_request_id": str(req_id),
            "idempotency_key": "conc-roll-resolve-1",
        },
    )
    assert roll_res["isError"] is False
    conc_data = roll_res["structuredContent"]["data"]
    # With damage 60, DC is 30, so roll cannot succeed and concentration is lost
    assert conc_data["succeeded"] is False
    reloaded_char = table.combat.character_repository.load_character(table.character_id)
    assert reloaded_char.state.concentration is None

    # Routing Item 16: calling generic roll_pending on that Concentration request id is refused
    generic_res = _mcp_call(
        client,
        player_token,
        "roll_pending",
        {
            "roll_request_id": str(req_id),
            "idempotency_key": "conc-plain-roll-attempt",
        },
    )
    assert generic_res["isError"] is True


def test_5_player_cast_spell_redaction_and_permission_denied_spy(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        facade,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)

    # 1. AI Player casts single-target spell via combat_cast_spell
    cast_res = _mcp_call(
        client,
        player_token,
        "combat_cast_spell",
        {
            "caster_entry_id": str(char_entry_id),
            "target_entry_id": str(mage_entry_id),
            "spell_ref": "srd5.1:spell:hold-person",
            "slot_level": 2,
            "idempotency_key": "test-5-cast-hp-1",
        },
    )
    assert cast_res["isError"] is False
    cast_data = cast_res["structuredContent"]["data"]
    assert cast_data["status"] == "resolved"
    res = cast_data["resolution_result"]
    assert res is not None
    # Player audience: target exact HP / AC / raw secrets are not leaked
    assert "target_hp" not in res or res.get("target_hp") is None
    assert "target_ac" not in res

    # 2. Spy pattern on DM-only facade methods
    spy_resolve_aoe = MagicMock(side_effect=facade.combat_resolve_aoe_spell)
    spy_open_reaction = MagicMock(side_effect=facade.combat_open_reaction_window)
    spy_resolve_adj = MagicMock(side_effect=facade.combat_resolve_adjudication)

    facade.combat_resolve_aoe_spell = spy_resolve_aoe
    facade.combat_open_reaction_window = spy_open_reaction
    facade.combat_resolve_adjudication = spy_resolve_adj

    # Player token attempts DM-only tools -> rejected before facade invocation
    aoe_res = _mcp_call(
        client,
        player_token,
        "combat_resolve_aoe_spell",
        {
            "action_id": str(uuid4()),
            "confirmed_target_ids": [str(mage_entry_id)],
        },
    )
    assert aoe_res["isError"] is True
    assert aoe_res["structuredContent"]["error"]["code"] == "permission_denied"
    assert spy_resolve_aoe.call_count == 0

    open_res = _mcp_call(
        client,
        player_token,
        "combat_open_reaction_window",
        {
            "entry_id": str(char_entry_id),
            "reason": "Test reaction",
        },
    )
    assert open_res["isError"] is True
    assert open_res["structuredContent"]["error"]["code"] == "permission_denied"
    assert spy_open_reaction.call_count == 0

    adj_res = _mcp_call(
        client,
        player_token,
        "combat_resolve_adjudication",
        {
            "action_id": str(uuid4()),
            "trigger": True,
            "ruling": "Disallowed",
        },
    )
    assert adj_res["isError"] is True
    assert adj_res["structuredContent"]["error"]["code"] == "permission_denied"
    assert spy_resolve_adj.call_count == 0


def test_6_opportunity_attack_reaction_lifecycle(mcp_combat_fixture) -> None:
    (
        table,
        char_entry_id,
        mage_entry_id,
        evil_mage,
        dm_token,
        player_token,
        facade,
        adj_service,
        res_repo,
    ) = mcp_combat_fixture

    client = TestClient(app)

    # 1. Player requests opportunity attack adjudication
    oa_req_res = _mcp_call(
        client,
        player_token,
        "combat_request_opportunity_attack",
        {
            "mover_entry_id": str(mage_entry_id),
            "reactor_entry_id": str(char_entry_id),
            "question": "Mage moved out of reach, may I take OA?",
            "idempotency_key": "test-6-oa-req",
        },
    )
    assert oa_req_res["isError"] is False
    action_id = oa_req_res["structuredContent"]["data"]["action_id"]

    # 2. DM resolves adjudication with trigger=True -> opens reaction window
    oa_resolve_res = _mcp_call(
        client,
        dm_token,
        "combat_resolve_adjudication",
        {
            "action_id": str(action_id),
            "trigger": True,
            "ruling": "Mage moved without Disengage",
            "idempotency_key": "test-6-oa-resolve",
        },
    )
    assert oa_resolve_res["isError"] is False

    # 3. Player's get_combat_context shows the open reaction window and next_required_action == "respond_to_reaction"
    p_ctx_res = _mcp_call(client, player_token, "get_combat_context", {})
    assert p_ctx_res["isError"] is False
    p_ctx = p_ctx_res["structuredContent"]["data"]
    assert len(p_ctx["reaction_windows"]) == 1
    assert p_ctx["reaction_windows"][0]["kind"] == "opportunity_attack"
    assert p_ctx["next_required_action"] == "respond_to_reaction"

    # 4. Player responds to reaction window via combat_respond_to_reaction
    react_res = _mcp_call(
        client,
        player_token,
        "combat_respond_to_reaction",
        {
            "owner_entry_id": str(char_entry_id),
            "accept": True,
            "idempotency_key": "test-6-react-accept",
        },
    )
    assert react_res["isError"] is False
    assert react_res["structuredContent"]["data"]["accepted"] is True

    # 5. Window is closed in player's get_combat_context
    p_ctx_after = _mcp_call(client, player_token, "get_combat_context", {})
    assert p_ctx_after["isError"] is False
    after_data = p_ctx_after["structuredContent"]["data"]
    assert len(after_data["reaction_windows"]) == 0
    assert after_data["next_required_action"] != "respond_to_reaction"
