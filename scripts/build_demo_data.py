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
import io
import json
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
EXAMPLES = ROOT / "examples"
DEMO = ROOT / "services" / "api" / "src" / "docentric_copilot" / "api" / "demo"
FIXED_TIME = (2024, 1, 1, 0, 0, 0)

LONG_ITEM_DESCRIPTIONS = (
    "Enterprise subscription for the finance and reporting suite, including twelve months of "
    "hosted updates, priority support, audit logs and unlimited read-only reviewer seats for "
    "European subsidiaries.",
    "Implementation workshop covering process discovery, template design, data mapping and a "
    "supervised go-live, delivered on site by two senior consultants with a written handover "
    "and follow-up review.",
)

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
    "quotation-long-items": {
        "package": "quotation/sales-quotation.ddsp",
        "prompt": "quotation/prompt.txt",
        "title": "Quotation with long item descriptions",
        "description": "Same brief, but two product descriptions are long enough to wrap over several table lines: use it to demo the text-fit check and Optimize layout.",
        "defect": "long_items",
        "long_descriptions": LONG_ITEM_DESCRIPTIONS,
    },
    "purchase-order": {
        "package": "purchase-order/purchase-order.ddsp",
        "prompt": "purchase-order/prompt.txt",
        "title": "Purchase order",
        "description": "Vendor block, ordered items with quantities and prices, delivery terms.",
    },
}


def _build_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _inject_long_descriptions(package: bytes, descriptions: tuple[str, ...]) -> bytes:
    """Return the same DDSP package with long sample descriptions in its lines.

    The schema and prompt stay byte-identical; only ``data/sample.xml`` changes,
    so the wrapped table is produced by real sample data rather than by a wider
    column. The archive is rebuilt deterministically.
    """
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        files = {name: archive.read(name) for name in archive.namelist()}
    root = ElementTree.fromstring(files["data/sample.xml"])
    lines = root.findall(".//QuotationLines/Line")
    for index, description in enumerate(descriptions):
        if index >= len(lines):
            break
        element = lines[index].find("Description")
        if element is None:
            element = ElementTree.SubElement(lines[index], "Description")
        element.text = description
    ElementTree.indent(root, space="  ")
    files["data/sample.xml"] = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        + ElementTree.tostring(root, encoding="utf-8")
        + b"\n"
    )
    return _build_zip(files)


def build() -> dict[str, bytes]:
    manifest = {"cases": []}
    files: dict[str, bytes] = {}
    for case_id, spec in CASES.items():
        package = (EXAMPLES / spec["package"]).read_bytes()
        if spec.get("long_descriptions"):
            package = _inject_long_descriptions(package, spec["long_descriptions"])
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
                **({"defect": spec["defect"]} if spec.get("defect") else {}),
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
