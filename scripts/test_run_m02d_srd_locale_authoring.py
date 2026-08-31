from __future__ import annotations

from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS_ROOT = Path(__file__).resolve().parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import run_m02d_srd_locale_authoring as runner


class M02DLocalAuthoringRunnerTests(unittest.TestCase):
    def test_reference_revision_remains_available_for_optional_reproducibility(self) -> None:
        self.assertEqual(
            runner.AUTHORING_REFERENCE_REPOSITORY,
            "hktrpg/fvtt-5e-classpack-zh-tw",
        )
        self.assertEqual(
            runner.AUTHORING_REFERENCE_COMMIT,
            "74276e1c4915d35b4d22539157fd49ef8717e105",
        )
        self.assertEqual(
            runner.AUTHORING_REFERENCE_SUBDIR,
            Path("translated-zh-tw/packs"),
        )

    def test_missing_reference_checkout_is_a_non_blocking_authoring_note(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing-reference"
            root, notes = runner.resolve_reference_root(
                missing,
                require_reference=False,
            )

        self.assertIsNone(root)
        self.assertEqual(len(notes), 1)
        self.assertIn("baseline dictionaries only", notes[0])

    def test_missing_reference_can_still_be_required_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing-reference"
            with self.assertRaisesRegex(ValueError, "baseline dictionaries only"):
                runner.resolve_reference_root(
                    missing,
                    require_reference=True,
                )

    def test_unresolved_markers_become_readable_text_and_review_items(self) -> None:
        overlay = {
            "entries": {
                "srd5.1:feature:test": {
                    "name": "〔未譯:Eldritch〕 Blast",
                }
            }
        }
        report = {
            "localized_entry_count": 1,
            "required_field_count": 1,
            "unknown_count": 1,
            "unknowns": [
                {
                    "key": "srd5.1:feature:test",
                    "field_path": "name",
                    "token": "Eldritch",
                    "value": "〔未譯:Eldritch〕 Blast",
                }
            ],
            "simplified_residue_count": 1,
            "simplified_residues": [
                {
                    "key": "srd5.1:feature:test",
                    "field_path": "name",
                    "characters": "术",
                    "value": "法术",
                }
            ],
        }

        candidate, human_report = runner.prepare_human_review_candidate(
            overlay,
            report,
            notes=["human review example"],
        )

        self.assertEqual(candidate["entries"]["srd5.1:feature:test"]["name"], "Eldritch Blast")
        self.assertEqual(candidate["review_status"], "draft-human-review-required")
        self.assertEqual(human_report["runtime_untranslated_marker_count"], 0)
        self.assertEqual(human_report["review_policy"], "human_review_required_non_blocking")
        self.assertEqual(human_report["review_item_count"], 2)
        self.assertEqual(
            {item["kind"] for item in human_report["review_items"]},
            {"unresolved_token", "possible_simplified_residue"},
        )

    def test_stablekey_human_override_wins_over_machine_same_name_collision(self) -> None:
        overlay = {
            "entries": {
                "srd5.1:equipment:shield": {"name": "護盾術"},
                "srd5.1:spell:shield": {"name": "護盾術"},
            }
        }
        report = {
            "localized_entry_count": 2,
            "required_field_count": 2,
            "unknown_count": 0,
            "unknowns": [],
            "simplified_residue_count": 0,
            "simplified_residues": [],
        }

        candidate, human_report = runner.prepare_human_review_candidate(
            overlay,
            report,
            stable_overrides={
                "srd5.1:equipment:shield": {"name": "盾牌"},
                "srd5.1:spell:shield": {"name": "護盾術"},
            },
        )

        self.assertEqual(candidate["entries"]["srd5.1:equipment:shield"]["name"], "盾牌")
        self.assertEqual(candidate["entries"]["srd5.1:spell:shield"]["name"], "護盾術")
        self.assertEqual(human_report["human_override_field_count"], 2)

    def test_reviewed_token_and_stable_override_sources_are_available(self) -> None:
        combined = runner.load_token_overrides()
        stable = runner.load_stable_overrides()

        self.assertTrue(combined)
        self.assertTrue(all(isinstance(key, str) for key in combined))
        self.assertTrue(all(isinstance(value, str) for value in combined.values()))
        self.assertEqual(stable["srd5.1:equipment:shield"]["name"], "盾牌")
        self.assertEqual(stable["srd5.1:spell:shield"]["name"], "護盾術")


if __name__ == "__main__":
    unittest.main()
