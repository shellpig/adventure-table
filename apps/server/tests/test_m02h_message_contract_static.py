from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]


def test_effective_builder_passes_preserve_structured_disabled_reason_identity() -> None:
    compiler = (ROOT / "apps/server/app/domain/character_builder/compiler.py").read_text(encoding="utf-8")
    assert "multiclass_option_failure_detail" in compiler
    assert "feat_failure_detail" in compiler
    assert '"disabled_reason_code": detail.code if detail is not None else None' in compiler
    assert '"disabled_reason_params": detail.params if detail is not None else {}' in compiler


def test_all_current_dynamic_disabled_reason_families_emit_codes() -> None:
    structural = (ROOT / "apps/server/app/domain/character_builder/structural.py").read_text(encoding="utf-8")
    progression = (ROOT / "apps/server/app/domain/character_builder/progression.py").read_text(encoding="utf-8")
    assert 'code="feat_prerequisite_not_met"' in structural
    assert '"nested_choice_parent_required"' in structural
    assert '"asi_ability_scores_incomplete"' in structural
    assert '"ability_score_cap_reached"' in structural
    assert '"asi_branch_required"' in structural
    assert "multiclass_option_failure_detail" in progression
