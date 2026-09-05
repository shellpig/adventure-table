"""Guard the pinned environment used to produce Windows standalone releases.

scripts\build-standalone.cmd calls this twice: once right after creating the
build venv to reject a wrong interpreter, and once after installing to reject a
package set that drifted from constraints-standalone-win.txt.
"""

from __future__ import annotations

import argparse
import platform
import re
import subprocess
import sys
from pathlib import Path

PYTHON_VERSION_PATTERN = re.compile(r"^#\s*python-version:\s*(\S+)$")


def canonical_name(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def load_constraints(path: Path) -> tuple[str, dict[str, str]]:
    expected_python: str | None = None
    pinned: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        header = PYTHON_VERSION_PATTERN.match(line)
        if header:
            expected_python = header.group(1)
            continue
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        if not separator:
            raise SystemExit(f"ERROR: constraints entry is not pinned with '==': {line}")
        pinned[canonical_name(name.strip())] = version.strip()
    if expected_python is None:
        raise SystemExit(f"ERROR: {path.name} has no '# python-version:' header.")
    return expected_python, pinned


def freeze_installed() -> dict[str, str]:
    result = subprocess.run(
        [sys.executable, "-m", "pip", "freeze", "--exclude-editable", "--all"],
        capture_output=True,
        text=True,
        check=True,
    )
    installed: dict[str, str] = {}
    for raw_line in result.stdout.splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        name, separator, version = line.partition("==")
        if not separator:
            raise SystemExit(f"ERROR: unexpected pip freeze output: {line}")
        installed[canonical_name(name.strip())] = version.strip()
    return installed


def check_python(expected_python: str) -> int:
    actual = platform.python_version()
    # The pin may be major.minor or a full patch version; compare only as many
    # components as the constraints file actually fixes.
    expected_parts = expected_python.split(".")
    if actual.split(".")[: len(expected_parts)] != expected_parts:
        print(
            f"ERROR: standalone releases are pinned to Python {expected_python}, "
            f"but this build is running Python {actual}.\n"
            "       Build with the pinned interpreter, or update "
            "constraints-standalone-win.txt and re-validate.",
            file=sys.stderr,
        )
        return 1
    print(f"[env] python {actual} matches constraints.")
    return 0


def check_packages(pinned: dict[str, str], installed: dict[str, str]) -> int:
    problems: list[str] = []
    for name, version in sorted(pinned.items()):
        if name not in installed:
            problems.append(f"  missing: {name}=={version}")
        elif installed[name] != version:
            problems.append(f"  version drift: {name} pinned {version}, installed {installed[name]}")
    for name, version in sorted(installed.items()):
        if name not in pinned:
            problems.append(f"  unpinned extra: {name}=={version}")
    if problems:
        print(
            "ERROR: the build environment does not match "
            "constraints-standalone-win.txt:",
            file=sys.stderr,
        )
        for problem in problems:
            print(problem, file=sys.stderr)
        print(
            "       Update the constraints file and re-validate before releasing.",
            file=sys.stderr,
        )
        return 1
    print(f"[env] {len(pinned)} pinned packages match constraints.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--constraints", required=True, type=Path)
    parser.add_argument("--mode", required=True, choices=("python", "packages"))
    args = parser.parse_args()

    expected_python, pinned = load_constraints(args.constraints)
    if args.mode == "python":
        return check_python(expected_python)
    return check_packages(pinned, freeze_installed())


if __name__ == "__main__":
    raise SystemExit(main())
