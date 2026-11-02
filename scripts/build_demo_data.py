#!/usr/bin/env python3
"""Copy the synthetic example packages into the API demo bundle.

The web workspace offers a one-click demo that must work from an installed wheel
and from the Docker image, neither of which ships the repository's ``examples/``
directory. The demo bundle is therefore package data, kept byte-identical with
the examples by this script.

Usage::

    python scripts/build_demo_data.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
DEMO = ROOT / "services" / "api" / "src" / "docentric_copilot" / "api" / "demo"

CASES = {
    "quotation": {
        "package": "quotation/sales-quotation.ddsp",
        "prompt": "quotation/prompt.txt",
        "title": "Sales quotation",
        "description": "Logo, customer block, item table, totals, VAT notice and bank details in the footer.",
    },
    "invoice": {
        "package": "invoice/sales-invoice.ddsp",
        "prompt": "invoice/prompt.txt",
        "title": "Tax invoice",
        "description": "Net, tax and gross totals, due date and a reverse-charge notice.",
    },
    "quotation-defect": {
        "package": "quotation/sales-quotation.ddsp",
        "prompt": "quotation/prompt.txt",
        "title": "Quotation with a layout defect",
        "description": "Same brief, but the item table is wider than the page: use it to demo the quality dashboard and Optimize layout.",
        "defect": True,
    },
    "purchase-order": {
        "package": "purchase-order/purchase-order.ddsp",
        "prompt": "purchase-order/prompt.txt",
        "title": "Purchase order",
        "description": "Vendor block, ordered items with quantities and prices, delivery terms.",
    },
}


def build() -> dict[str, bytes]:
    manifest = {"cases": []}
    files: dict[str, bytes] = {}
    for case_id, spec in CASES.items():
        package = (EXAMPLES / spec["package"]).read_bytes()
        prompt = (EXAMPLES / spec["prompt"]).read_text(encoding="utf-8").strip()
        filename = f"{case_id}.ddsp"
        files[filename] = package
        manifest["cases"].append(
            {
                "id": case_id,
                "title": spec["title"],
                "description": spec["description"],
                "package": filename,
                "prompt": prompt,
                **({"defect": True} if spec.get("defect") else {}),
            }
        )
    files["manifest.json"] = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode()
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if the bundle is out of date")
    args = parser.parse_args(argv)

    failures = 0
    for name, content in build().items():
        path = DEMO / name
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                print(f"out of date: {path.relative_to(ROOT)}")
                failures += 1
        else:
            DEMO.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"wrote {path.relative_to(ROOT)}")
    if args.check and failures:
        print(f"{failures} demo file(s) out of date", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
