from __future__ import annotations

from pathlib import Path
from typing import Iterable

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import Revision


SERVER_ROOT = Path(__file__).resolve().parents[1]
CHARACTER_HEAD = "0009_p2a_character_head"
WEB_HEAD = "0010_p2a_web_rooms"
BRANCH_POINT = "0008_m03c_import_records"


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


def test_p2a_character_and_web_tracks_are_distinct_heads() -> None:
    scripts = _scripts()
    assert set(scripts.get_heads()) == {CHARACTER_HEAD, WEB_HEAD}

    character = scripts.get_revision(CHARACTER_HEAD)
    web = scripts.get_revision(WEB_HEAD)
    assert character is not None
    assert web is not None
    assert character.down_revision == BRANCH_POINT
    assert web.down_revision == BRANCH_POINT
    assert "character" in character.branch_labels
    assert "web" in web.branch_labels
    assert character.dependencies is None
    assert web.dependencies is None


def test_p2a_character_head_ancestry_never_reaches_web_track() -> None:
    scripts = _scripts()
    character_ancestry = _revision_ids(
        scripts.walk_revisions(base="base", head=CHARACTER_HEAD)
    )
    web_ancestry = _revision_ids(scripts.walk_revisions(base="base", head=WEB_HEAD))

    assert BRANCH_POINT in character_ancestry
    assert BRANCH_POINT in web_ancestry
    assert WEB_HEAD not in character_ancestry
    assert CHARACTER_HEAD not in web_ancestry
    assert character_ancestry - web_ancestry == {CHARACTER_HEAD}
    assert web_ancestry - character_ancestry == {WEB_HEAD}


def test_p2a_split_has_no_cross_track_dependency_or_merge() -> None:
    scripts = _scripts()
    character = scripts.get_revision(CHARACTER_HEAD)
    web = scripts.get_revision(WEB_HEAD)
    assert character is not None
    assert web is not None

    # P2-A starts as two independent descendants of the M03 branch point.
    # Later Web revisions may depend on Character revisions, but the Character
    # track must never depend on Web and the two lineages must never be merged.
    assert not (_references(character.dependencies) & {WEB_HEAD})
    assert not (_references(character.down_revision) & {WEB_HEAD})
    assert not (
        _references(web.down_revision) & {CHARACTER_HEAD}
        and _references(character.down_revision) & {WEB_HEAD}
    )
    assert len(_references(character.down_revision)) == 1
    assert len(_references(web.down_revision)) == 1


def test_p2a_alembic_env_does_not_import_room_metadata_unconditionally() -> None:
    source = (SERVER_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "app.persistence.rooms" not in source
    assert "app.domain.rooms" not in source
