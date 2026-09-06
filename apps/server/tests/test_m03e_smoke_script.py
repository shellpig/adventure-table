from __future__ import annotations

from pathlib import Path
import runpy
from typing import Callable, cast


REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = REPO_ROOT / "scripts/smoke_standalone.py"


def test_smoke_script_reads_character_alembic_revision_head() -> None:
    namespace = runpy.run_path(str(SMOKE_SCRIPT))
    migration_head = cast(Callable[[Path], str], namespace["_migration_head"])

    assert migration_head(REPO_ROOT) == "0009_p2a_character_head"
