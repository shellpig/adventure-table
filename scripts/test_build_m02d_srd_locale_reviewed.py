from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import build_m02d_srd_locale_reviewed as reviewed


class M02DReviewedLocaleTests(unittest.TestCase):
    def test_canonical_names_reads_current_top_level_srd_arrays(self) -> None:
        names = reviewed._canonical_names()

        self.assertTrue(names)
        self.assertIn("Light Hammer", names.values())
        self.assertIn("Wizard", names.values())

    def test_whole_name_reference_fixes_marker_free_composition(self) -> None:
        base_overlay = {
            "schema_version": 1,
            "locale": "zh-TW",
            "entries": {
                "srd5.1:equipment:light-hammer": {"name": "光明錘"},
                "srd5.1:class:wizard": {"name": "法師"},
            },
        }
        base_report = {
            "localized_entry_count": 2,
            "required_field_count": 2,
            "unknown_count": 0,
            "unknowns": [],
        }
        canonical_names = {
            "srd5.1:equipment:light-hammer": "Light Hammer",
            "srd5.1:class:wizard": "Wizard",
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "light-hammer.json").write_text(
                json.dumps({"name": "輕錘 Light Hammer"}, ensure_ascii=False),
                encoding="utf-8",
            )
            # Deliberately conflicting with the project glossary. The project
            # exact translation must still win.
            (root / "wizard.json").write_text(
                json.dumps({"name": "外部法師 Wizard"}, ensure_ascii=False),
                encoding="utf-8",
            )

            with patch.object(
                reviewed.base,
                "build_overlay",
                return_value=(deepcopy(base_overlay), deepcopy(base_report)),
            ), patch.object(reviewed, "_canonical_names", return_value=canonical_names):
                overlay, report = reviewed.build_reviewed_overlay(root, {})

        self.assertEqual(
            overlay["entries"]["srd5.1:equipment:light-hammer"]["name"],
            "輕錘",
        )
        self.assertEqual(
            overlay["entries"]["srd5.1:class:wizard"]["name"],
            "法師",
        )
        self.assertEqual(report["exact_reference_hits"], 1)
        self.assertEqual(report["project_exact_name_hits"], 1)

    def test_structured_spell_scroll_name_beats_external_reference(self) -> None:
        key = "srd5.1:item:spell-scroll-4th"
        base_overlay = {
            "schema_version": 1,
            "locale": "zh-TW",
            "entries": {key: {"name": "法術卷軸4〔未譯:th〕等級"}},
        }
        base_report = {
            "localized_entry_count": 1,
            "required_field_count": 1,
            "unknown_count": 1,
            "unknowns": [{"key": key, "canonical": "Spell Scroll 4th Level", "token": "th"}],
        }

        with tempfile.TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            (root / "scroll.json").write_text(
                json.dumps(
                    {"name": "外部第四環卷軸 Spell Scroll 4th Level"},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            with patch.object(
                reviewed.base,
                "build_overlay",
                return_value=(deepcopy(base_overlay), deepcopy(base_report)),
            ), patch.object(
                reviewed,
                "_canonical_names",
                return_value={key: "Spell Scroll 4th Level"},
            ):
                overlay, report = reviewed.build_reviewed_overlay(root, {"th": ""})

        self.assertEqual(overlay["entries"][key]["name"], "4環法術卷軸")
        self.assertEqual(report["structured_name_hits"], 1)
        self.assertEqual(report["unknown_count"], 0)

    def test_possessive_candidates_recover_reviewed_dictionary_form(self) -> None:
        self.assertIn("hunter's", reviewed._token_candidates("Hunters"))
        self.assertIn("alchemist's", reviewed._token_candidates("Alchemists"))

    def test_simplified_residue_gate_is_conservative(self) -> None:
        overlay = {
            "entries": {
                "srd5.1:spell:test": {"name": "法术"},
                "srd5.1:equipment:lyre": {"name": "里拉琴"},
            }
        }

        residues = reviewed._simplified_residues(overlay)

        self.assertEqual(len(residues), 1)
        self.assertEqual(residues[0]["characters"], "术")
        self.assertEqual(residues[0]["key"], "srd5.1:spell:test")


if __name__ == "__main__":
    unittest.main()
