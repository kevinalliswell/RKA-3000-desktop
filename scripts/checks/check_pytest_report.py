"""Validate a pytest JUnit XML report.

PySide6 can segfault during Qt's C++ teardown at interpreter exit on headless CI
(after every test has already passed and the report is written). That corrupts the
process exit code but not the results. CI therefore derives its verdict from this
report rather than from pytest's exit code: a clean report passes; a missing/empty
report (e.g. a real mid-run crash) or any failure/error fails.
"""

from __future__ import annotations

import sys
import xml.etree.ElementTree as ET
from pathlib import Path


def main(path_str: str) -> int:
    path = Path(path_str)
    if not path.exists():
        print(f"pytest report not found: {path}", file=sys.stderr)
        return 1

    root = ET.parse(path).getroot()
    total = failures = errors = 0
    for suite in root.iter("testsuite"):
        total += int(suite.get("tests", "0"))
        failures += int(suite.get("failures", "0"))
        errors += int(suite.get("errors", "0"))

    if total == 0:
        print("no tests were collected (possible crash before/during collection)", file=sys.stderr)
        return 1
    if failures or errors:
        print(f"pytest reported {failures} failures, {errors} errors", file=sys.stderr)
        return 1

    print(f"pytest report OK: {total} tests, 0 failures, 0 errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else "pytest-report.xml"))
