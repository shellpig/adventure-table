from __future__ import annotations

from pathlib import Path
from typing import Iterable

from alembic.config import Config
from alembic.script import ScriptDirectory
from alembic.script.revision import Revision


SERVER_ROOT = Path(__file__).resolve().parents[1]
CHARACTER_ROOT = "0009_p2a_character_head"
P2A_WEB_ROOT = "0010_p2a_web_rooms"
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


def _ancestry(scripts: ScriptDirectory, head: str) -> set[str]:
    return _revision_ids(scripts.walk_revisions(base="base", head=head))


def _track_head(scripts: ScriptDirectory, root: str) -> str:
    matches = [head for head in scripts.get_heads() if root in _ancestry(scripts, head)]
    assert len(matches) == 1, f"expected exactly one head descending from {root}, got {matches}"
    return matches[0]


def _track_revisions(
    scripts: ScriptDirectory,
    *,
    head: str,
    other_head: str,
) -> set[str]:
    return _ancestry(scripts, head) - _ancestry(scripts, other_head)


def test_p2a_character_and_web_tracks_remain_distinct_at_current_heads() -> None:
    scripts = _scripts()
    character_head_id = _track_head(scripts, CHARACTER_ROOT)
    web_head_id = _track_head(scripts, P2A_WEB_ROOT)

    assert character_head_id != web_head_id
    assert set(scripts.get_heads()) == {character_head_id, web_head_id}

    character_root = scripts.get_revision(CHARACTER_ROOT)
    p2a_web = scripts.get_revision(P2A_WEB_ROOT)
    character_head = scripts.get_revision(character_head_id)
    web_head = scripts.get_revision(web_head_id)
    assert character_root is not None
    assert p2a_web is not None
    assert character_head is not None
    assert web_head is not None
    assert character_root.down_revision == BRANCH_POINT
    assert p2a_web.down_revision == BRANCH_POINT
    assert "character" in character_root.branch_labels
    assert "web" in p2a_web.branch_labels
    assert character_root.dependencies is None
    assert p2a_web.dependencies is None


def test_p2a_character_head_ancestry_never_reaches_web_track() -> None:
    scripts = _scripts()
    character_head = _track_head(scripts, CHARACTER_ROOT)
    web_head = _track_head(scripts, P2A_WEB_ROOT)
    character_ancestry = _ancestry(scripts, character_head)
    web_ancestry = _ancestry(scripts, web_head)
    character_track = _track_revisions(
        scripts,
        head=character_head,
        other_head=web_head,
    )
    web_track = _track_revisions(
        scripts,
        head=web_head,
        other_head=character_head,
    )

    assert BRANCH_POINT in character_ancestry
    assert BRANCH_POINT in web_ancestry
    assert CHARACTER_ROOT in character_track
    assert P2A_WEB_ROOT in web_track
    assert P2A_WEB_ROOT not in character_ancestry
    assert CHARACTER_ROOT not in web_ancestry
    assert character_track.isdisjoint(web_track)


def test_p2a_split_has_no_cross_track_dependency_or_merge() -> None:
    scripts = _scripts()
    character_head = _track_head(scripts, CHARACTER_ROOT)
    web_head = _track_head(scripts, P2A_WEB_ROOT)
    character_track = _track_revisions(
        scripts,
        head=character_head,
        other_head=web_head,
    )
    web_track = _track_revisions(
        scripts,
        head=web_head,
        other_head=character_head,
    )

    for revision_id in character_track:
        revision = scripts.get_revision(revision_id)
        assert revision is not None
        assert not (_references(revision.dependencies) & web_track)
        assert not (_references(revision.down_revision) & web_track)
        assert len(_references(revision.down_revision)) == 1

    for revision_id in web_track:
        revision = scripts.get_revision(revision_id)
        assert revision is not None
        assert not (_references(revision.dependencies) & character_track)
        assert not (_references(revision.down_revision) & character_track)
        assert len(_references(revision.down_revision)) == 1


def test_p2a_alembic_env_does_not_import_room_metadata_unconditionally() -> None:
    source = (SERVER_ROOT / "alembic" / "env.py").read_text(encoding="utf-8")
    assert "app.persistence.rooms" not in source
    assert "app.domain.rooms" not in source
