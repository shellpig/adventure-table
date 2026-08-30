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
    def test_reference_revision_is_explicitly_pinned(self) -> None:
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

    def test_missing_reference_checkout_fails_before_generation(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            missing = Path(temp_dir) / "missing-reference"
            with self.assertRaisesRegex(ValueError, "missing Traditional Chinese authoring reference"):
                runner.verify_reference_checkout(missing)

    def test_reviewed_token_sources_are_available_and_string_only(self) -> None:
        combined = runner.load_token_overrides()

        self.assertTrue(combined)
        self.assertTrue(all(isinstance(key, str) for key in combined))
        self.assertTrue(all(isinstance(value, str) for value in combined.values()))


if __name__ == "__main__":
    unittest.main()
