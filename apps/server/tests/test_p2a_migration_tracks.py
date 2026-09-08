from __future__ import annotations

from pathlib import Path
from typing import Iterable

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import Revision


SERVER_ROOT = Path(__file__).resolve().parents[1]
CHARACTER_ROOT = "0009_p2a_character_head"
CHARACTER_HEAD = "0015_character_state_revision"
P2A_WEB_ROOT = "0010_p2a_web_rooms"
P2B_WEB_REVISION = "0011_p2b_room_workspace"
P2C_WEB_REVISION = "0012_p2c_campaigns"
P2D_WEB_REVISION = "0013_p2d_campaign_seats"
WEB_HEAD = "0014_p2e_sessions"
BRANCH_POINT = "0008_m03c_import_records"
WEB_REVISIONS = {
    P2A_WEB_ROOT,
    P2B_WEB_REVISION,
    P2C_WEB_REVISION,
    P2D_WEB_REVISION,
    WEB_HEAD,
}


def _scripts() -> ScriptDirectory:
    config = Config(str(SERVER_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(SERVER_ROOT / "alembic"))
    return ScriptDirectory.from_config(config)


def _revision_ids(revisions: Iterable[Revision]) -> set[str]:
    return {revision.revision for revision in revisions}


def _references(value: str | tuple[str, ...] | None) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {value}
    return set(value)


def test_p2a_character_and_web_tracks_remain_distinct_at_current_heads() -> None:
    scripts = _scripts()
    assert set(scripts.get_heads()) == {CHARACTER_HEAD, WEB_HEAD}

    character_root = scripts.get_revision(CHARACTER_ROOT)
    character_head = scripts.get_revision(CHARACTER_HEAD)
    p2a_web = scripts.get_revision(P2A_WEB_ROOT)
    p2b_web = scripts.get_revision(P2B_WEB_REVISION)
    p2c_web = scripts.get_revision(P2C_WEB_REVISION)
    p2d_web = scripts.get_revision(P2D_WEB_REVISION)
    web_head = scripts.get_revision(WEB_HEAD)
    assert character_root is not None
    assert character_head is not None
    assert p2a_web is not None
    assert p2b_web is not None
    assert p2c_web is not None
    assert p2d_web is not None
    assert web_head is not None
    assert character_root.down_revision == BRANCH_POINT
    assert character_head.down_revision == CHARACTER_ROOT
    assert p2a_web.down_revision == BRANCH_POINT
    assert p2b_web.down_revision == P2A_WEB_ROOT
    assert p2c_web.down_revision == P2B_WEB_REVISION
    assert p2d_web.down_revision == P2C_WEB_REVISION
    assert web_head.down_revision == P2D_WEB_REVISION
    assert "character" in character_root.branch_labels
    assert "character" in character_head.branch_labels
    assert "web" in p2a_web.branch_labels
    assert character_root.dependencies is None
    assert character_head.dependencies is None
    assert p2a_web.dependencies is None
    assert p2b_web.dependencies is None
    assert p2c_web.dependencies is None
    assert p2d_web.dependencies is None
    assert web_head.dependencies is None


def test_p2a_character_head_ancestry_never_reaches_web_track() -> None:
    scripts = _scripts()
    character_ancestry = _revision_ids(
        scripts.walk_revisions(base="base", head=CHARACTER_HEAD)
    )
    web_ancestry = _revision_ids(scripts.walk_revisions(base="base", head=WEB_HEAD))

    assert BRANCH_POINT in character_ancestry
    assert BRANCH_POINT in web_ancestry
    assert not (WEB_REVISIONS & character_ancestry)
    assert CHARACTER_ROOT not in web_ancestry
    assert CHARACTER_HEAD not in web_ancestry
    assert character_ancestry - web_ancestry == {CHARACTER_ROOT, CHARACTER_HEAD}
    assert web_ancestry - character_ancestry == WEB_REVISIONS


def test_p2a_split_has_no_cross_track_dependency_or_merge() -> None:
    scripts = _scripts()
    character_root = scripts.get_revision(CHARACTER_ROOT)
    character_head = scripts.get_revision(CHARACTER_HEAD)
    p2a_web = scripts.get_revision(P2A_WEB_ROOT)
    p2b_web = scripts.get_revision(P2B_WEB_REVISION)
    p2c_web = scripts.get_revision(P2C_WEB_REVISION)
    p2d_web = scripts.get_revision(P2D_WEB_REVISION)
    web_head = scripts.get_revision(WEB_HEAD)
    assert character_root is not None
    assert character_head is not None
    assert p2a_web is not None
    assert p2b_web is not None
    assert p2c_web is not None
    assert p2d_web is not None
    assert web_head is not None

    assert not (_references(character_root.dependencies) & WEB_REVISIONS)
    assert not (_references(character_root.down_revision) & WEB_REVISIONS)
    assert not (_references(character_head.dependencies) & WEB_REVISIONS)
    assert not (_references(character_head.down_revision) & WEB_REVISIONS)
    assert character_head.down_revision == CHARACTER_ROOT
    assert p2a_web.down_revision == BRANCH_POINT
    assert p2b_web.down_revision == P2A_WEB_ROOT
    assert p2c_web.down_revision == P2B_WEB_REVISION
    assert p2d_web.down_revision == P2C_WEB_REVISION
    assert web_head.down_revision == P2D_WEB_REVISION
    assert CHARACTER_ROOT not in _references(p2a_web.dependencies)
    assert CHARACTER_ROOT not in _references(p2b_web.dependencies)
    assert CHARACTER_ROOT not in _references(p2c_web.dependencies)
    assert CHARACTER_ROOT not in _references(p2d_web.dependencies)
    assert CHARACTER_ROOT not in _references(web_head.dependencies)
    assert CHARACTER_HEAD not in _references(p2a_web.dependencies)
    assert CHARACTER_HEAD not in _references(p2b_web.dependencies)
    assert CHARACTER_HEAD not in _references(p2c_web.dependencies)
    assert CHARACTER_HEAD not in _references(p2d_web.dependencies)
    assert CHARACTER_HEAD not in _references(web_head.dependencies)
    assert len(_references(character_root.down_revision)) == 1
    assert len(_references(character_head.down_revision)) == 1
    assert len(_references(p2a_web.down_revision)) == 1
    assert len(_references(p2b_web.down_revision)) == 1
    assert len(_references(p2c_web.down_revision)) == 1
    assert len(_references(p2d_web.down_revision)) == 1
    assert len(_references(web_head.down_revision)) == 1


def test_p2a_alembic_env_does_not_import_room_metadata_unconditionally() -> None:
    source = (SERVER_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "app.persistence.rooms" not in source
    assert "app.domain.rooms" not in source
