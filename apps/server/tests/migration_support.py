from __future__ import annotations

from alembic.config import Config
from alembic.script import ScriptDirectory


def migration_heads(config: Config) -> dict[str, str]:
    """Require one head per supported branch without pinning revision IDs."""
    scripts = ScriptDirectory.from_config(config)
    heads: dict[str, str] = {}
    for revision_id in scripts.get_heads():
        revision = scripts.get_revision(revision_id)
        assert revision is not None
        assert len(revision.branch_labels) == 1, (
            f"head {revision_id} must belong to exactly one branch: {revision.branch_labels}"
        )
        branch, = revision.branch_labels
        assert branch not in heads, f"multiple heads for {branch}: {heads[branch]}, {revision_id}"
        heads[branch] = revision_id
    assert set(heads) == {"character", "web"}, f"unexpected migration branches: {heads}"
    return heads
