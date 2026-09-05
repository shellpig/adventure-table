from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "m03-standalone.yml"
NON_E2E_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "m03f-non-e2e.yml"
RELEASE_NOTES = REPO_ROOT / "docs" / "M03" / "release-notes-template.md"


def _workflow_text() -> str:
    assert WORKFLOW.is_file(), "M03-F standalone workflow is missing"
    return WORKFLOW.read_text(encoding="utf-8")


def _non_e2e_text() -> str:
    assert NON_E2E_WORKFLOW.is_file(), "M03-F non-E2E workflow is missing"
    return NON_E2E_WORKFLOW.read_text(encoding="utf-8")


def _release_job_text() -> str:
    text = _workflow_text()
    marker = "\n  release:\n"
    assert marker in text, "M03-F release job is missing"
    return text.split(marker, 1)[1]


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


def test_m03f_release_job_has_explicit_repository_context_and_checked_out_notes() -> None:
    release = _release_job_text()

    # gh CLI commands are not allowed to depend on cwd inference alone.  Keep
    # both an explicit GH_REPO and checkout because the release notes template
    # is a repository file consumed by the job.
    assert "GH_REPO: ${{ github.repository }}" in release
    assert release.index("actions/checkout@v4") < release.index("gh release view")
    assert RELEASE_NOTES.is_file(), "M03-F release notes template is missing"
    assert "--notes-file docs/M03/release-notes-template.md" in release


def test_m03f_release_job_is_tag_only_writable_and_marks_schema_unstable() -> None:
    release = _release_job_text()
    notes = RELEASE_NOTES.read_text(encoding="utf-8")

    assert "if: startsWith(github.ref, 'refs/tags/v')" in release
    assert "permissions:\n      contents: write" in release
    assert "gh release create" in release
    assert "gh release upload" in release
    assert "--clobber" in release
    assert "schema is **unstable** during M03" in notes


def test_m03f_release_asset_name_matches_build_script_contract() -> None:
    workflow = _workflow_text()
    build_script = (REPO_ROOT / "scripts" / "build-standalone.cmd").read_text(encoding="utf-8")

    assert "adventure-table-standalone-%VERSION%.zip" in build_script
    assert "adventure-table-standalone-$VERSION.zip" in workflow
    assert "needs.standalone-build.outputs.version" in workflow


def test_m03f_non_e2e_gate_is_manual_by_trigger_commit_and_contains_no_e2e() -> None:
    text = _non_e2e_text()

    assert "m03-f-windows-ci-release-boundary" in text
    assert ".github/m03f-non-e2e.trigger" in text
    assert "test_m03_import_boundary.py" in text
    assert "test_m03_standalone_composition.py" in text
    assert "test_m03f_workflow_contract.py" in text
    assert "scripts\\build-standalone.cmd --version m03f-non-e2e" in text
    assert "scripts\\smoke_standalone.py dist\\adventure-table-standalone --timeout 30" in text
    assert "test:e2e" not in text.lower()
    assert "playwright" not in text.lower()
