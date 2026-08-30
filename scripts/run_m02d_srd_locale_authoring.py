"""Generate a human-reviewable M02-D SRD zh-TW draft locally.

M02-D translation is intentionally human-first. The deterministic dictionaries
and optional community reference are drafting aids, not an authority on final
Traditional Chinese D&D terminology. The normal workflow is therefore:

1. generate a readable baseline;
2. write review diagnostics for uncertain/mixed-language output;
3. let a human reviewer correct terminology in a follow-up pass.

Unknown tokens and possible Simplified-Chinese residue are review findings, not
release blockers by default. Only structural failures (invalid JSON, malformed
source data, unwritable output, etc.) stop generation.

Optional Traditional Chinese reference:
- repository: hktrpg/fvtt-5e-classpack-zh-tw
- reviewed commit: 74276e1c4915d35b4d22539157fd49ef8717e105
- data root: translated-zh-tw/packs

If that checkout is absent, generation still succeeds using the project-owned
baseline dictionaries. If a caller explicitly needs reproducibility against the
reference, pass ``--require-reference``.

The generated ``data/srd5.1/locales/zh-TW.json`` is a static presentation
overlay. Runtime code never reads the external reference checkout.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
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
UNTRANSLATED_RE = re.compile(r"〔未譯:([^〕]+)〕")


def _load_json_object(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"expected JSON object: {path}")
    return payload


def load_token_overrides() -> dict[str, str]:
    """Combine project drafting dictionaries in their historical override order."""

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


def resolve_reference_root(
    checkout: Path,
    *,
    require_reference: bool,
) -> tuple[Path | None, list[str]]:
    """Return a pinned reference when available, otherwise a review note.

    The optional community pack improves a first draft but does not define the
    project's final terminology. Missing or mismatched references are therefore
    non-blocking unless the caller explicitly asks for reproducibility.
    """

    notes: list[str] = []
    if not checkout.is_dir():
        message = (
            "Traditional Chinese authoring reference is not checked out; "
            "using project baseline dictionaries only."
        )
        if require_reference:
            raise ValueError(
                f"{message} Clone {AUTHORING_REFERENCE_REPOSITORY} at "
                f"{AUTHORING_REFERENCE_COMMIT}."
            )
        notes.append(message)
        return None, notes

    head = reference_head(checkout)
    if head != AUTHORING_REFERENCE_COMMIT:
        message = (
            "Traditional Chinese authoring reference is on an unreviewed commit "
            f"({head}); expected {AUTHORING_REFERENCE_COMMIT}. Reference ignored."
        )
        if require_reference:
            raise ValueError(message)
        notes.append(message)
        return None, notes

    packs = checkout / AUTHORING_REFERENCE_SUBDIR
    if not packs.is_dir():
        message = f"Traditional Chinese reference data root is missing: {packs}. Reference ignored."
        if require_reference:
            raise ValueError(message)
        notes.append(message)
        return None, notes
    return packs, notes


def _make_readable(value: Any) -> Any:
    """Remove machine-only unresolved markers while preserving readable fallback text."""

    if isinstance(value, str):
        return UNTRANSLATED_RE.sub(lambda match: match.group(1), value)
    if isinstance(value, list):
        return [_make_readable(item) for item in value]
    if isinstance(value, dict):
        return {key: _make_readable(item) for key, item in value.items()}
    return value


def prepare_human_review_candidate(
    overlay: dict[str, Any],
    report: dict[str, Any],
    *,
    notes: list[str] | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Convert machine diagnostics into a readable baseline plus review queue."""

    readable_overlay = _make_readable(overlay)
    unknowns = list(report.get("unknowns", []))
    simplified = list(report.get("simplified_residues", []))
    review_items = [
        {
            "kind": "unresolved_token",
            **item,
        }
        for item in unknowns
        if isinstance(item, dict)
    ]
    review_items.extend(
        {
            "kind": "possible_simplified_residue",
            **item,
        }
        for item in simplified
        if isinstance(item, dict)
    )
    human_report = {
        **report,
        "review_policy": "human_review_required_non_blocking",
        "authoring_notes": list(notes or []),
        "review_item_count": len(review_items),
        "review_items": review_items,
        "runtime_untranslated_marker_count": 0,
    }
    return readable_overlay, human_report


def write_candidate(
    reference_checkout: Path,
    output: Path,
    report_path: Path,
    *,
    require_reference: bool = False,
    fail_on_review_findings: bool = False,
    check_against: Path | None = None,
) -> int:
    reference_root, notes = resolve_reference_root(
        reference_checkout,
        require_reference=require_reference,
    )
    token_overrides = load_token_overrides()
    raw_overlay, raw_report = reviewed.build_reviewed_overlay(reference_root, token_overrides)
    overlay, report = prepare_human_review_candidate(raw_overlay, raw_report, notes=notes)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(overlay, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    failed = False
    if check_against is not None:
        committed = _load_json_object(check_against)
        if committed != overlay:
            print(f"DRIFT generated overlay differs from {check_against}")
            failed = True

    review_count = int(report.get("review_item_count", 0))
    if review_count:
        print(f"REVIEW {review_count} item(s) queued for human terminology review")
        if fail_on_review_findings:
            failed = True
    for note in report.get("authoring_notes", []):
        print(f"NOTE {note}")

    print(
        "M02-D human-review baseline: "
        f"{report['localized_entry_count']} entries / "
        f"{report['required_field_count']} required fields / "
        f"{review_count} review items / "
        "0 runtime unresolved markers"
    )
    print(f"OUTPUT {output}")
    print(f"REPORT {report_path}")
    return 2 if failed else 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate a readable M02-D SRD zh-TW baseline for human review.",
    )
    parser.add_argument(
        "--reference-checkout",
        type=Path,
        default=DEFAULT_REFERENCE_CHECKOUT,
        help="optional checkout of hktrpg/fvtt-5e-classpack-zh-tw",
    )
    parser.add_argument(
        "--require-reference",
        action="store_true",
        help="fail when the optional reference checkout is absent or not at the reviewed commit",
    )
    parser.add_argument(
        "--fail-on-review-findings",
        action="store_true",
        help="optional maintainer mode: make review diagnostics return a non-zero exit code",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    parser.add_argument(
        "--check-against",
        type=Path,
        help="fail if the generated baseline differs from this existing overlay",
    )
    args = parser.parse_args()

    try:
        return write_candidate(
            args.reference_checkout,
            args.output,
            args.report,
            require_reference=args.require_reference,
            fail_on_review_findings=args.fail_on_review_findings,
            check_against=args.check_against,
        )
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        parser.error(str(exc))
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
