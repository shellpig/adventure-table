from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "m03-standalone.yml"


def _workflow_text() -> str:
    assert WORKFLOW.is_file(), "M03-F standalone workflow is missing"
    return WORKFLOW.read_text(encoding="utf-8")


def test_m03f_workflow_has_required_triggers_and_windows_toolchain() -> None:
    text = _workflow_text()

    assert "branches:\n      - main" in text
    assert "tags:\n      - 'v*'" in text
    assert "pull_request:\n    types:\n      - labeled" in text
    assert "github.event.label.name == 'standalone-build'" in text
    assert "runs-on: windows-latest" in text
    assert 'python-version: "3.13"' in text
    assert 'node-version: "24"' in text


def test_m03f_windows_job_builds_smokes_and_uploads_the_zip() -> None:
    text = _workflow_text()

    assert "scripts\\build-standalone.cmd --version" in text
    assert "scripts\\smoke_standalone.py dist\\adventure-table-standalone --timeout 30" in text
    assert "actions/upload-artifact@v4" in text
    assert "dist/adventure-table-standalone-${{ steps.version.outputs.value }}.zip" in text
    assert "if-no-files-found: error" in text
    # F.1 explicitly requires the default exe-adjacent SQLite path to be the
    # subject under test, not something supplied by the runner environment.
    assert "ADVENTURE_TABLE_DATABASE_PATH" not in text


def test_m03f_release_job_is_tag_only_writable_and_marks_schema_unstable() -> None:
    text = _workflow_text()

    assert "if: startsWith(github.ref, 'refs/tags/v')" in text
    assert "permissions:\n      contents: write" in text
    assert "gh release create" in text
    assert "--notes-file release-notes.txt" in text
    assert "gh release upload" in text
    assert "--clobber" in text
    assert "Character JSON schema is unstable during M03" in text


def test_m03f_release_asset_name_matches_build_script_contract() -> None:
    workflow = _workflow_text()
    build_script = (REPO_ROOT / "scripts" / "build-standalone.cmd").read_text(encoding="utf-8")

    assert "adventure-table-standalone-%VERSION%.zip" in build_script
    assert "adventure-table-standalone-$VERSION.zip" in workflow
    assert "needs.standalone-build.outputs.version" in workflow
