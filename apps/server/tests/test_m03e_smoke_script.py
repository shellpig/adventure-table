from __future__ import annotations

from pathlib import Path
import runpy
from typing import Callable, cast

from alembic.config import Config

from tests.migration_support import migration_heads


REPO_ROOT = Path(__file__).resolve().parents[3]
SMOKE_SCRIPT = REPO_ROOT / "scripts/smoke_standalone.py"


def test_smoke_script_reads_character_alembic_revision_head() -> None:
    namespace = runpy.run_path(str(SMOKE_SCRIPT))
    migration_head = cast(Callable[[Path], str], namespace["_migration_head"])

    server_root = REPO_ROOT / "apps" / "server"
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    assert migration_head(REPO_ROOT) == migration_heads(config)["character"]
