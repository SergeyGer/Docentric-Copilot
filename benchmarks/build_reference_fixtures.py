#!/usr/bin/env python3
"""Write or verify the synthetic REF-05 fixtures and ``reference_cases.json``.

Usage::

    .venv/bin/python benchmarks/build_reference_fixtures.py
    .venv/bin/python benchmarks/build_reference_fixtures.py --check
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:  # pragma: no cover - script bootstrap
    sys.path.insert(0, str(ROOT))

from benchmarks.reference_fixtures import build_all  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if a fixture is out of date")
    args = parser.parse_args(argv)

    failures = 0
    for relative, content in sorted(build_all().items()):
        target = ROOT / relative
        if args.check:
            if not target.exists() or target.read_bytes() != content:
                print(f"out of date: {relative}")
                failures += 1
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        print(f"wrote {relative}")
    if args.check and failures:
        print(f"{failures} fixture file(s) out of date", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
