from __future__ import annotations

from pathlib import Path
import shutil
import subprocess
import sys

import m01k_support as S
from app.content import load_default_content_registry
from app.content.localization_files import load_content_localization_catalog
from app.paths import resolve_content_root

ROOT = Path(__file__).resolve().parents[3]
APP_ROOT = Path(__file__).resolve().parents[1] / "app"

EXPECTED_FEAT_KEYS = [
    # XGE (15)
    "xge:feat:bountiful-luck",
    "xge:feat:dragon-fear",
    "xge:feat:dragon-hide",
    "xge:feat:drow-high-magic",
    "xge:feat:dwarven-fortitude",
    "xge:feat:elven-accuracy",
    "xge:feat:fade-away",
    "xge:feat:fey-teleportation",
    "xge:feat:flames-of-phlegethos",
    "xge:feat:infernal-constitution",
    "xge:feat:orcish-fury",
    "xge:feat:prodigy",
    "xge:feat:second-chance",
    "xge:feat:squat-nimbleness",
    "xge:feat:wood-elf-magic",
    # TCE (15)
    "tce:feat:artificer-initiate",
    "tce:feat:chef",
    "tce:feat:crusher",
    "tce:feat:eldritch-adept",
    "tce:feat:fey-touched",
    "tce:feat:fighting-initiate",
    "tce:feat:gunner",
    "tce:feat:metamagic-adept",
    "tce:feat:piercer",
    "tce:feat:poisoner",
    "tce:feat:shadow-touched",
    "tce:feat:skill-expert",
    "tce:feat:slasher",
    "tce:feat:telekinetic",
    "tce:feat:telepathic",
]


def test_m01o_inventory_verifier_script_passes() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "verify_m01o_feat_inventory.py")],
        cwd=ROOT,
        check=False,
        text=True,
        capture_output=True,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert "XGE 15 / TCE 15 / total 30" in result.stdout


def test_runtime_does_not_read_reference_markdown(tmp_path: Path, monkeypatch) -> None:
    # 1. Static assert: Scan all .py in apps/server/app/
    # No app code may reference "暫用規則資訊" or "docs/"
    for py_file in APP_ROOT.rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert "暫用規則資訊" not in text, f"{py_file.name} references 暫用規則資訊"
        assert "docs/" not in text, f"{py_file.name} references docs/"

    # 2. Dynamic assert: copy content root to tmp_path (which does not contain docs/)
    real_content_root = resolve_content_root()
    tmp_content_root = tmp_path / "data"
    shutil.copytree(real_content_root, tmp_content_root)
    assert not (tmp_path / "docs").exists()

    monkeypatch.setenv("ADVENTURE_TABLE_CONTENT_ROOT", str(tmp_content_root))

    S.registry.cache_clear()
    try:
        assert resolve_content_root() == tmp_content_root
        registry = load_default_content_registry()

        # Assert all 30 feats exist in registry
        for key in EXPECTED_FEAT_KEYS:
            assert registry.get_optional(key) is not None, f"missing {key} without docs"

        # Assert _available_result compiles and exposes feat opportunities
        base = S.auto_fill(
            S.payload(S.levels_for(S.FIGHTER_L4), race="srd5.1:race:human"),
            registry,
        )
        avail_res, _ = S.compile_payload(base, registry)
        opps = S.feat_opportunities(avail_res)
        assert len(opps) >= 1

        # Assert Prodigy child choices expand and compile cleanly
        res_prodigy, _, opp_id = S.feat_draft(
            "xge:feat:prodigy",
            nested={
                "skill": ("srd5.1:proficiency:skill-investigation",),
                "tool": ("srd5.1:proficiency:thieves-tools",),
                "language": ("srd5.1:language:elvish",),
                "expertise": ("srd5.1:skill:investigation",),
            },
            content=registry,
        )
        assert S.issue_codes(res_prodigy) == set()
        assert res_prodigy.build_candidate is not None

        skill_choice = S.choice_by_id(res_prodigy, S.child_choice_id(opp_id, "skill"))
        tool_choice = S.choice_by_id(res_prodigy, S.child_choice_id(opp_id, "tool"))
        language_choice = S.choice_by_id(res_prodigy, S.child_choice_id(opp_id, "language"))
        expertise_choice = S.choice_by_id(res_prodigy, S.child_choice_id(opp_id, "expertise"))
        assert skill_choice is not None
        assert tool_choice is not None
        assert language_choice is not None
        assert expertise_choice is not None

        # Assert localization catalog resolves "奇才" and "Prodigy"
        catalog = load_content_localization_catalog(registry, resolve_content_root())
        zh_field = catalog.resolve_name("xge:feat:prodigy", "zh-TW")
        en_field = catalog.resolve_name("xge:feat:prodigy", "en")
        assert zh_field.value == "奇才"
        assert not zh_field.fallback_used
        assert en_field.value == "Prodigy"
        assert not en_field.fallback_used
    finally:
        S.registry.cache_clear()
