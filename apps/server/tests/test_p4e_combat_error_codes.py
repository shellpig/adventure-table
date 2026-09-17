from __future__ import annotations

from app.api.rooms.combat import _map_combat_error
from app.api.rooms.combat_reactions import _map_error as _map_reactions_error
from app.api.rooms.combat_special_attacks import _map_error as _map_special_attacks_error
from app.api.rooms.combat_spells import _map_error as _map_spells_error
from app.domain.combat.concentration import CombatConcentrationNotFoundError
from app.domain.combat.lifecycle import CombatNotFoundError
from app.domain.combat.reaction_service import CombatReactionNotFoundError
from app.domain.combat.special_attacks import SpecialAttackNotFoundError
from app.domain.combat.spell_service import CombatSpellNotFoundError

COMBAT_MAPPER_CODES = frozenset({
    "session_not_found",
    "table_actor_unauthorized",
    "session_not_active",
    "unknown_reference",
    "monster_instance_conflict",
    "combat_not_found",
    "attack_not_found",
    "combat_roll_not_found",
    "combat_target_not_found",
    "active_combat_exists",
    "combat_state_conflict",
    "initiative_request_not_found",
    "invalid_initiative_input",
    "invalid_attack_definition",
    "invalid_combat_input",
    "character_not_found",
})

REACTIONS_MAPPER_CODES = frozenset({
    "session_not_found",
    "table_actor_unauthorized",
    "session_not_active",
    "combat_not_found",
    "combat_state_conflict",
    "invalid_combat_input",
})

SPELLS_MAPPER_CODES = frozenset({
    "session_not_found",
    "table_actor_unauthorized",
    "session_not_active",
    "combat_not_found",
    "combat_state_conflict",
    "invalid_combat_input",
})

SPECIAL_ATTACKS_MAPPER_CODES = frozenset({
    "session_not_found",
    "table_actor_unauthorized",
    "session_not_active",
    "combat_not_found",
    "special_attack_not_found",
    "combat_state_conflict",
    "invalid_combat_input",
})

ALL_COMBAT_ROUTER_CODES = (
    COMBAT_MAPPER_CODES
    | REACTIONS_MAPPER_CODES
    | SPELLS_MAPPER_CODES
    | SPECIAL_ATTACKS_MAPPER_CODES
)

PRE_P4E_SHARED_CODES = frozenset({
    "session_not_found",
    "table_actor_unauthorized",
    "session_not_active",
    "character_not_found",
})

EXPECTED_P4E_SESSION_CODES = frozenset({
    "unknown_reference",
    "monster_instance_conflict",
    "combat_not_found",
    "attack_not_found",
    "combat_roll_not_found",
    "combat_target_not_found",
    "active_combat_exists",
    "combat_state_conflict",
    "initiative_request_not_found",
    "invalid_initiative_input",
    "invalid_attack_definition",
    "invalid_combat_input",
    "special_attack_not_found",
})


def test_map_combat_error_not_found_mappings() -> None:
    err1 = _map_combat_error(CombatNotFoundError("combat missing"))
    assert err1.status_code == 404
    assert err1.code == "combat_not_found"

    err2 = _map_combat_error(CombatReactionNotFoundError("reaction missing"))
    assert err2.status_code == 404
    assert err2.code == "combat_not_found"


def test_map_reactions_error_not_found_mappings() -> None:
    err1 = _map_reactions_error(CombatNotFoundError("combat missing"))
    assert err1.status_code == 404
    assert err1.code == "combat_not_found"

    err2 = _map_reactions_error(CombatReactionNotFoundError("reaction missing"))
    assert err2.status_code == 404
    assert err2.code == "combat_not_found"


def test_map_spells_error_not_found_mappings() -> None:
    err1 = _map_spells_error(CombatNotFoundError("combat missing"))
    assert err1.status_code == 404
    assert err1.code == "combat_not_found"

    err2 = _map_spells_error(CombatSpellNotFoundError("spell missing"))
    assert err2.status_code == 404
    assert err2.code == "combat_not_found"

    err3 = _map_spells_error(CombatConcentrationNotFoundError("concentration missing"))
    assert err3.status_code == 404
    assert err3.code == "combat_not_found"


def test_map_special_attacks_error_not_found_mappings() -> None:
    err1 = _map_special_attacks_error(CombatNotFoundError("combat missing"))
    assert err1.status_code == 404
    assert err1.code == "combat_not_found"

    err2 = _map_special_attacks_error(SpecialAttackNotFoundError("special attack missing"))
    assert err2.status_code == 404
    assert err2.code == "special_attack_not_found"


def test_all_combat_mappers_emitted_codes_match_expected_p4_set() -> None:
    assert ALL_COMBAT_ROUTER_CODES == PRE_P4E_SHARED_CODES | EXPECTED_P4E_SESSION_CODES
    assert ALL_COMBAT_ROUTER_CODES - PRE_P4E_SHARED_CODES == EXPECTED_P4E_SESSION_CODES
