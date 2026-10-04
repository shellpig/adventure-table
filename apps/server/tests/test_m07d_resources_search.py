"""M07-D D1: custom-template instance resources (F05), bilingual search (F10).

F05: building an Instance from a custom template seeds spell slots exactly
like the built-in path (``initial_monster_resources``).
F10: custom-template search matches supported-locale names and searchable
type fields, excluding English long-text ``desc`` — parity with builtin.
"""

from __future__ import annotations

from uuid import UUID, uuid4

from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.content.registry import resolve_content_root
from app.domain.combat.monster_instances import (
    CreateMonsterFromContentInput,
    MonsterInstanceService,
)
from app.domain.monster_library.schemas import CreateCustomMonsterFromContentInput
from app.domain.monster_library.service import MonsterLibraryService
from app.domain.rooms.schemas import RoomAccessAuthority, RoomAccessContext
from app.persistence.combat.repository import MonsterRepository
from app.persistence.monster_library.repository import MonsterLibraryRepository
from tests.p5a_tactical_helpers import TacticalTable, setup_tactical_table

ACOLYTE_KEY = "srd5.1:monster:acolyte"
GOBLIN_KEY = "srd5.1:monster:goblin"


def _table_with_library() -> tuple[TacticalTable, MonsterLibraryService, RoomAccessContext]:
    table = setup_tactical_table()
    registry = load_default_content_registry()
    localization = load_content_localization_catalog(registry, resolve_content_root())
    library = MonsterLibraryService(
        table.engine,
        MonsterLibraryRepository(table.engine),
        MonsterRepository(table.engine),
        registry,
        localization,
        table.events,
    )
    owner = RoomAccessContext(
        room_id=table.room_id,
        access_session_id=table.dm_actor.access_session_id,
        authority=RoomAccessAuthority.OWNER,
        display_name="Owner",
    )
    return table, library, owner


def _instances(table: TacticalTable) -> MonsterInstanceService:
    return MonsterInstanceService(
        monster_repository=table.combat.monster_repository,
        content_registry=table.registry,
        table_event_service=table.events,
    )


# --- F05 ---------------------------------------------------------------------------------


def test_custom_template_instance_seeds_spell_slots() -> None:
    table, library, owner = _table_with_library()
    template = library.create_from_content(
        owner, table.room_id,
        CreateCustomMonsterFromContentInput(content_key=ACOLYTE_KEY),
    )
    template_id = UUID(template.ref.removeprefix("custom:"))
    view = _instances(table).create_from_content(
        table.dm_actor,
        CreateMonsterFromContentInput(content_key=f"custom:{template_id}"),
    )
    assert view.resources.get("spell_slot:1") == 3


def test_custom_template_instance_matches_builtin_resources() -> None:
    table, library, owner = _table_with_library()
    template = library.create_from_content(
        owner, table.room_id,
        CreateCustomMonsterFromContentInput(content_key=ACOLYTE_KEY),
    )
    template_id = UUID(template.ref.removeprefix("custom:"))
    service = _instances(table)
    from_custom = service.create_from_content(
        table.dm_actor,
        CreateMonsterFromContentInput(
            content_key=f"custom:{template_id}", idempotency_key="d1-res-a"
        ),
    )
    from_builtin = service.create_from_content(
        table.dm_actor,
        CreateMonsterFromContentInput(
            content_key=ACOLYTE_KEY, idempotency_key="d1-res-b"
        ),
    )
    assert from_custom.resources == from_builtin.resources
    assert from_custom.resources.get("spell_slot:1") == 3


# --- F10 ---------------------------------------------------------------------------------


def _copy_goblin(table: TacticalTable, library: MonsterLibraryService, owner: RoomAccessContext) -> UUID:
    template = library.create_from_content(
        owner, table.room_id,
        CreateCustomMonsterFromContentInput(content_key=GOBLIN_KEY),
    )
    assert template.name == "Goblin"
    assert template.name_is_custom is False
    return UUID(template.ref.removeprefix("custom:"))


def test_custom_search_matches_zh_name() -> None:
    table, library, owner = _table_with_library()
    custom_id = _copy_goblin(table, library, owner)
    hits = library.list_for_actor(table.dm_actor, table.room_id, query="地精")
    refs = {item.ref for item in hits}
    assert "srd5.1:monster:goblin" in refs
    assert f"custom:{custom_id}" in refs


def test_custom_search_matches_english_name_and_type() -> None:
    table, library, owner = _table_with_library()
    custom_id = _copy_goblin(table, library, owner)
    hits = library.list_for_actor(table.dm_actor, table.room_id, query="goblin")
    assert f"custom:{custom_id}" in {item.ref for item in hits}
    type_hits = library.list_for_actor(table.dm_actor, table.room_id, query="humanoid")
    assert f"custom:{custom_id}" in {item.ref for item in type_hits}


def test_custom_search_excludes_english_desc() -> None:
    table, library, owner = _table_with_library()
    custom_id = _copy_goblin(table, library, owner)
    # "Disengage" appears only in the copied Nimble Escape ability desc.
    hits = library.list_for_actor(table.dm_actor, table.room_id, query="Disengage")
    assert f"custom:{custom_id}" not in {item.ref for item in hits}


def test_custom_search_source_filter_still_applies() -> None:
    table, library, owner = _table_with_library()
    custom_id = _copy_goblin(table, library, owner)
    hits = library.list_for_actor(
        table.dm_actor, table.room_id, query="地精", source="custom"
    )
    refs = {item.ref for item in hits}
    assert f"custom:{custom_id}" in refs
    assert "srd5.1:monster:goblin" not in refs
