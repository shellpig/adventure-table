from __future__ import annotations

import asyncio
from types import SimpleNamespace
from uuid import uuid4

from app.domain.combat.ai_tools import CombatAIToolApplicationService, CombatRollToolInput
from app.domain.combat.attacks import AttackRequestInput
from app.domain.combat.resolution import DamageType
from app.domain.combat.semantic_hp import SemanticDamageInput
from app.domain.rooms.ai_controllers import AIControllerAuthView
from app.domain.rooms.rolls import FormalRollInput, FormalRollSource
from app.mcp.tools import call_tool, tool_catalog


def _auth(role: str) -> AIControllerAuthView:
    return AIControllerAuthView(
        grant_id=uuid4(),
        room_id=uuid4(),
        campaign_id=uuid4(),
        seat_id=uuid4(),
        role=role,
        session_id=uuid4(),
        generation=1,
        is_current_dm=role == "dm",
    )


def test_mcp_combat_catalog_enforces_role_surface() -> None:
    player_names = {item["name"] for item in tool_catalog(_auth("player"))}
    dm_names = {item["name"] for item in tool_catalog(_auth("dm"))}

    shared = {
        "combat_get_active",
        "combat_list_attacks",
        "combat_request_attack",
        "combat_roll_attack",
        "combat_apply_damage",
        "combat_apply_healing",
        "combat_roll_saving_throw",
        "combat_request_death_save",
        "combat_roll_death_save",
        "combat_request_special_attack",
        "combat_roll_special_attack",
    }
    assert shared <= player_names
    assert shared <= dm_names

    dm_only = {
        "combat_adjudicate_attack",
        "combat_request_saving_throws",
        "combat_adjudicate_special_attack",
    }
    assert dm_only <= dm_names
    assert not (dm_only & player_names)


class _DispatchSpy:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object, object]] = []

    def combat_request_attack(self, token, parsed, *, authenticated=None):
        self.calls.append((token, parsed, authenticated))
        return {"delegated": True, "source_ref": parsed.source_ref}

    def combat_adjudicate_attack(self, token, parsed, *, authenticated=None):
        raise AssertionError("player role must be rejected before service dispatch")


def test_mcp_dispatch_only_validates_then_delegates_to_combat_facade() -> None:
    auth = _auth("player")
    service = _DispatchSpy()
    attacker = uuid4()
    target = uuid4()

    response = asyncio.run(
        call_tool(
            service,  # type: ignore[arg-type]
            token="ai-token",
            auth=auth,
            name="combat_request_attack",
            arguments={
                "attacker_entry_id": str(attacker),
                "target_entry_id": str(target),
                "source_ref": "inventory:longsword",
                "idempotency_key": "mcp-attack",
            },
        )
    )

    assert response["isError"] is False
    assert response["structuredContent"]["data"]["delegated"] is True
    assert len(service.calls) == 1
    token, parsed, seen_auth = service.calls[0]
    assert token == "ai-token"
    assert seen_auth == auth
    assert isinstance(parsed, AttackRequestInput)
    assert parsed.attacker_entry_id == attacker
    assert parsed.target_entry_id == target

    forbidden = asyncio.run(
        call_tool(
            service,  # type: ignore[arg-type]
            token="ai-token",
            auth=auth,
            name="combat_adjudicate_attack",
            arguments={"action_id": str(uuid4()), "in_range": True},
        )
    )
    assert forbidden["isError"] is True
    assert forbidden["structuredContent"]["error"]["code"] == "permission_denied"
    assert len(service.calls) == 1


class _FacadeUnderTest(CombatAIToolApplicationService):
    actor = object()

    def _actor(self, token: str, *, authenticated=None):  # type: ignore[override]
        assert token == "ai-token"
        return self.actor


class _AttackServiceSpy:
    def __init__(self) -> None:
        self.actor = None
        self.input: FormalRollInput | None = None

    def complete_attack(self, actor, input: FormalRollInput):
        self.actor = actor
        self.input = input
        return SimpleNamespace(
            model_dump=lambda **_kwargs: {
                "action_id": str(uuid4()),
                "hit": True,
                "critical": False,
            }
        )


class _DamageServiceSpy:
    def __init__(self) -> None:
        self.actor = None
        self.input: SemanticDamageInput | None = None

    def apply_damage(self, actor, input: SemanticDamageInput):
        self.actor = actor
        self.input = input
        return SimpleNamespace(
            event_id=uuid4(),
            combat_id=uuid4(),
            target_entry_id=input.target_entry_id,
            kind="damage",
            before_hp=20,
            after_hp=13,
            before_temp_hp=0,
            after_temp_hp=0,
            amount=input.amount,
            payload={"damage_type": input.damage_type.value},
        )


def test_mcp_facade_uses_server_formal_roll_and_shared_attack_service() -> None:
    facade = object.__new__(_FacadeUnderTest)
    spy = _AttackServiceSpy()
    facade.combat_attack_service = spy
    request_id = uuid4()

    result = facade.combat_roll_attack(
        "ai-token",
        CombatRollToolInput(
            roll_request_id=request_id,
            idempotency_key="mcp-roll",
        ),
    )

    assert result["hit"] is True
    assert spy.actor is facade.actor
    assert spy.input is not None
    assert spy.input.roll_request_id == request_id
    assert spy.input.source is FormalRollSource.SERVER
    assert spy.input.raw_dice is None
    assert spy.input.idempotency_key == "mcp-roll"


def test_mcp_facade_forwards_semantic_damage_without_recalculating_hp() -> None:
    facade = object.__new__(_FacadeUnderTest)
    spy = _DamageServiceSpy()
    facade.combat_resolution_service = spy
    target = uuid4()
    request = SemanticDamageInput(
        target_entry_id=target,
        amount=7,
        damage_type=DamageType.FIRE,
        idempotency_key="mcp-damage",
    )

    result = facade.combat_apply_damage("ai-token", request)

    assert spy.actor is facade.actor
    assert spy.input is request
    assert result["target_entry_id"] == str(target)
    assert result["amount"] == 7
    assert result["before_hp"] == 20
    assert result["after_hp"] == 13
    assert result["payload"] == {"damage_type": "fire"}
