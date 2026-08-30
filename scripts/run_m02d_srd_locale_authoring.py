"""Run the complete M02-D SRD zh-TW authoring pass locally.

This replaces the temporary GitHub Actions authoring workflow. It deliberately
never clones or downloads anything itself: the Traditional Chinese reference
must be checked out locally at the exact pinned commit, then this runner verifies
that commit before generating the runtime overlay.

Reference pin:
- repository: hktrpg/fvtt-5e-classpack-zh-tw
- commit: 74276e1c4915d35b4d22539157fd49ef8717e105
- data root: translated-zh-tw/packs

Example setup from the repository root:

    git clone https://github.com/hktrpg/fvtt-5e-classpack-zh-tw.git \
      _reference/fvtt-5e-classpack-zh-tw
    git -C _reference/fvtt-5e-classpack-zh-tw checkout \
      74276e1c4915d35b4d22539157fd49ef8717e105
    python scripts/run_m02d_srd_locale_authoring.py

The generated ``data/srd5.1/locales/zh-TW.json`` remains a static presentation
overlay. Runtime code never reads the external reference checkout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

SCRIPTS_ROOT = Path(__file__).resolve().parent
ROOT = SCRIPTS_ROOT.parent
if str(SCRIPTS_ROOT) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_ROOT))

import build_m02d_srd_locale_reviewed as reviewed

AUTHORING_REFERENCE_REPOSITORY = "hktrpg/fvtt-5e-classpack-zh-tw"
AUTHORING_REFERENCE_COMMIT = "74276e1c4915d35b4d22539157fd49ef8717e105"
AUTHORING_REFERENCE_SUBDIR = Path("translated-zh-tw/packs")
DEFAULT_REFERENCE_CHECKOUT = ROOT / "_reference" / "fvtt-5e-classpack-zh-tw"
DEFAULT_OUTPUT = ROOT / "data" / "srd5.1" / "locales" / "zh-TW.json"
DEFAULT_REPORT = ROOT / "data" / "localization" / "m02d-srd-zh-tw-report.json"
TOKEN_OVERRIDE_PATHS = (
    ROOT / "data" / "localization" / "m02d-srd-zh-tw-token-overrides.json",
    ROOT / "data" / "localization" / "m02d-srd-zh-tw-token-overrides-singletons.json",
    ROOT / "data" / "localization" / "m02d-srd-zh-tw-token-aliases.json",
)


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_token_overrides() -> dict[str, str]:
    """Combine reviewed token dictionaries in the historical authoring order."""

    combined: dict[str, str] = {}
    for path in TOKEN_OVERRIDE_PATHS:
        raw = _load_json_object(path)
        if not all(isinstance(key, str) and isinstance(value, str) for key, value in raw.items()):
            raise ValueError(f"token override file must contain string pairs: {path}")
        combined.update(raw)
    return combined


def reference_head(checkout: Path) -> str:
    try:
        result = subprocess.run(
            ["git", "-C", str(checkout), "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"cannot read reference checkout git HEAD: {checkout}") from exc
    return result.stdout.strip()


def verify_reference_checkout(checkout: Path) -> Path:
    """Require the exact reviewed reference revision before authoring output."""

    if not checkout.is_dir():
        raise ValueError(
            "missing Traditional Chinese authoring reference checkout: "
            f"{checkout}\n"
            f"clone {AUTHORING_REFERENCE_REPOSITORY} and checkout "
            f"{AUTHORING_REFERENCE_COMMIT}"
        )
    head = reference_head(checkout)
    if head != AUTHORING_REFERENCE_COMMIT:
        raise ValueError(
            "Traditional Chinese authoring reference commit mismatch: "
            f"expected {AUTHORING_REFERENCE_COMMIT}, got {head}"
        )
    packs = checkout / AUTHORING_REFERENCE_SUBDIR
    if not packs.is_dir():
        raise ValueError(f"reference data root does not exist: {packs}")
    return packs


def write_candidate(
    reference_checkout: Path,
    output: Path,
    report_path: Path,
    *,
    check_against: Path | None = None,
) -> int:
    reference_root = verify_reference_checkout(reference_checkout)
    token_overrides = load_token_overrides()
    overlay, report = reviewed.build_reviewed_overlay(reference_root, token_overrides)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    failed = False
    if report.get("reference_name_count", 0) == 0:
        print("REFERENCE no unambiguous Traditional Chinese names were loaded")
        failed = True
    if report.get("unknown_count", 0):
        print(f"UNKNOWN {report['unknown_count']} unresolved translation marker(s)")
        failed = True
    if report.get("simplified_residue_count", 0):
        print(f"SIMPLIFIED {report['simplified_residue_count']} residue(s)")
        failed = True

    if check_against is not None:
        committed = _load_json_object(check_against)
        if committed != overlay:
            print(f"DRIFT generated overlay differs from {check_against}")
            failed = True

    print(
        "M02-D local authoring: "
        f"{report['localized_entry_count']} entries / "
        f"{report['required_field_count']} required fields / "
        f"{report.get('unknown_count', 0)} unknown / "
        f"{report.get('simplified_residue_count', 0)} simplified residues"
    )
    print(f"OUTPUT {output}")
    print(f"REPORT {report_path}")
    return 2 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate the reviewed M02-D SRD zh-TW runtime overlay locally.",
    )
    parser.add_argument(
        "--reference-checkout",
        type=Path,
        default=DEFAULT_REFERENCE_CHECKOUT,
        help=(
            "checkout of hktrpg/fvtt-5e-classpack-zh-tw; its HEAD must equal "
            f"{AUTHORING_REFERENCE_COMMIT}"
        ),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--check-against",
        type=Path,
        help="also fail if generated JSON differs from this existing overlay",
    )
    args = parser.parse_args()

    try:
        return write_candidate(
            args.reference_checkout,
            args.output,
            args.report,
            check_against=args.check_against,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
