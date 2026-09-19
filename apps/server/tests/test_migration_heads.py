from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import shutil
from types import ModuleType

from alembic.config import Config
from alembic.script import ScriptDirectory
import pytest

from tests import (
    test_m03e_smoke_script,
    test_m04b_oauth_schema,
    test_p3c_migration_contract,
    test_p3d_migration_contract,
    test_p4b_postgres_migration,
    test_p4c_postgres_migration,
    test_p4e_postgres_migration,
    test_p4f_postgres_migration,
)
from tests.migration_support import migration_heads


@pytest.fixture
def extended_migrations(tmp_path: Path) -> Path:
    server_root = Path(__file__).resolve().parents[1]
    copied_root = tmp_path / "apps" / "server"
    shutil.copytree(
        server_root / "alembic",
        copied_root / "alembic",
        ignore=shutil.ignore_patterns("__pycache__"),
    )
    shutil.copy2(server_root / "alembic.ini", copied_root / "alembic.ini")
    config = Config(str(copied_root / "alembic.ini"))
    config.set_main_option("script_location", str(copied_root / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    for branch in ("character", "web"):
        parent = scripts.get_revision(f"{branch}@head")
        assert parent is not None
        (copied_root / "alembic" / "versions" / f"future_{branch}.py").write_text(
            f"revision = 'future_{branch}'\n"
            f"down_revision = {parent.revision!r}\n"
            "branch_labels = None\n"
            "def upgrade():\n    pass\n"
            "def downgrade():\n    pass\n",
            encoding="utf-8",
        )
    return tmp_path


@pytest.mark.parametrize(
    ("module", "contract"),
    [
        (
            test_m03e_smoke_script,
            test_m03e_smoke_script.test_smoke_script_reads_character_alembic_revision_head,
        ),
        (
            test_m04b_oauth_schema,
            test_m04b_oauth_schema.test_m04b_revision_links_p3d_and_carries_forward_to_current_web_head,
        ),
        (
            test_p3c_migration_contract,
            test_p3c_migration_contract.test_p3c_web_migration_chain_links_check_command_into_current_head,
        ),
        (
            test_p3d_migration_contract,
            test_p3d_migration_contract.test_p3d_revision_carries_forward_to_current_web_head,
        ),
        *[
            pytest.param(module, contract, marks=module.pytestmark)
            for module, contract in (
                (test_p4b_postgres_migration, test_p4b_postgres_migration.test_p4b_schema_survives_fresh_upgrade_to_heads),
                (test_p4c_postgres_migration, test_p4c_postgres_migration.test_p4c_schema_survives_fresh_upgrade_to_heads),
                (test_p4e_postgres_migration, test_p4e_postgres_migration.test_p4e_schema_survives_fresh_upgrade_to_heads),
                (test_p4f_postgres_migration, test_p4f_postgres_migration.test_p4f_schema_survives_fresh_upgrade_to_heads),
            )
        ],
    ],
    ids=lambda value: value.__name__,
)
def test_existing_contract_accepts_future_branch_heads(
    extended_migrations: Path,
    monkeypatch: pytest.MonkeyPatch,
    module: ModuleType,
    contract: Callable[[], None],
) -> None:
    server_root = extended_migrations / "apps" / "server"
    monkeypatch.setattr(module, "__file__", str(server_root / "tests" / "contract.py"))
    if module is test_m03e_smoke_script:
        monkeypatch.setattr(module, "REPO_ROOT", extended_migrations)
    elif module in (
        test_p4b_postgres_migration,
        test_p4c_postgres_migration,
        test_p4e_postgres_migration,
        test_p4f_postgres_migration,
    ):
        monkeypatch.setattr(module, "SERVER_ROOT", server_root)
    contract()


@pytest.mark.parametrize("branch", ["character", "web"])
def test_migration_heads_rejects_a_fork_with_two_heads(
    extended_migrations: Path,
    branch: str,
) -> None:
    server_root = extended_migrations / "apps" / "server"
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    scripts = ScriptDirectory.from_config(config)
    current = scripts.get_revision(f"{branch}@head")
    assert current is not None
    (server_root / "alembic" / "versions" / "fork.py").write_text(
        "revision = 'fork'\n"
        f"down_revision = {current.down_revision!r}\n"
        "branch_labels = None\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match=f"multiple heads for {branch}"):
        migration_heads(config)


def test_migration_heads_rejects_an_unlabelled_extra_head(extended_migrations: Path) -> None:
    server_root = extended_migrations / "apps" / "server"
    config = Config(str(server_root / "alembic.ini"))
    config.set_main_option("script_location", str(server_root / "alembic"))
    (server_root / "alembic" / "versions" / "unlabelled.py").write_text(
        "revision = 'unlabelled'\ndown_revision = None\nbranch_labels = None\n",
        encoding="utf-8",
    )

    with pytest.raises(AssertionError, match="must belong to exactly one branch"):
        migration_heads(config)
