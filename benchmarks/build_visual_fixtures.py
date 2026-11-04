#!/usr/bin/env python3
"""Build deterministic DDSP fixtures for the visual-regression golden cases.

The three fixtures reuse the bundled ``examples/quotation`` schema and differ
only in their synthetic sample data:

* ``quotation-long-items`` - two descriptions long enough to wrap over several
  table lines (the same idea as the API demo case);
* ``quotation-40-rows`` - forty line items, so the table spans several pages;
* ``quotation-empty-lines`` - a valid package whose ``QuotationLines`` contains
  no ``Line`` elements (the empty-collection case).

The schema, prompt and manifest stay byte-identical to the example. Only
``data/sample.xml`` changes, and the ZIP is rebuilt with fixed timestamps so the
committed bytes are reproducible.

Usage::

    python benchmarks/build_visual_fixtures.py
    python benchmarks/build_visual_fixtures.py --check
"""

from __future__ import annotations

import argparse
import copy
import io
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree

ROOT = Path(__file__).resolve().parent.parent
SOURCE = ROOT / "examples" / "quotation" / "sales-quotation.ddsp"
FIXTURES = ROOT / "benchmarks" / "fixtures"
FIXED_TIME = (2024, 1, 1, 0, 0, 0)

LONG_DESCRIPTIONS = (
    "Enterprise subscription for the finance and reporting suite, including twelve months of "
    "hosted updates, priority support, audit logs and unlimited read-only reviewer seats for "
    "European subsidiaries.",
    "Implementation workshop covering process discovery, template design, data mapping and a "
    "supervised go-live, delivered on site by two senior consultants with a written handover "
    "and follow-up review.",
)

ROW_DESCRIPTION = (
    "Line item for the visual-regression fixture with enough words to wrap once in the "
    "description column and make the repeated header visible on every page."
)


def _read_files(package: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(package)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def _build_zip(files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(files):
            info = zipfile.ZipInfo(name, date_time=FIXED_TIME)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, files[name])
    return buffer.getvalue()


def _sample_root(files: dict[str, bytes]) -> ElementTree.Element:
    return ElementTree.fromstring(files["data/sample.xml"])


def _write_sample(files: dict[str, bytes], root: ElementTree.Element) -> None:
    ElementTree.indent(root, space="  ")
    files["data/sample.xml"] = (
        b'<?xml version="1.0" encoding="utf-8"?>\n'
        + ElementTree.tostring(root, encoding="utf-8")
        + b"\n"
    )


def _long_items(package: bytes) -> bytes:
    files = _read_files(package)
    root = _sample_root(files)
    lines = root.findall(".//QuotationLines/Line")
    for line, description in zip(lines, LONG_DESCRIPTIONS, strict=False):
        element = line.find("Description")
        if element is not None:
            element.text = description
    _write_sample(files, root)
    return _build_zip(files)


def _forty_rows(package: bytes) -> bytes:
    files = _read_files(package)
    root = _sample_root(files)
    container = root.find(".//QuotationLines")
    if container is None:  # pragma: no cover - fixture contract
        raise SystemExit("quotation sample has no QuotationLines element")
    template = container.find("Line")
    if template is None:  # pragma: no cover - fixture contract
        raise SystemExit("quotation sample has no Line element")
    for child in list(container):
        if child.tag == "Line":
            container.remove(child)
    for index in range(1, 41):
        line = copy.deepcopy(template)
        values = {
            "ItemId": f"ITEM-{index:03d}",
            "Description": f"{ROW_DESCRIPTION} Item {index:03d}.",
            "Quantity": str(1 + index % 3),
            "Unit": "pcs",
            "UnitPrice": f"{12.5 + index * 3.25:.2f}",
            "LineAmount": f"{(1 + index % 3) * (12.5 + index * 3.25):.2f}",
        }
        for key, value in values.items():
            element = line.find(key)
            if element is not None:
                element.text = value
        container.append(line)
    _write_sample(files, root)
    return _build_zip(files)


def _empty_lines(package: bytes) -> bytes:
    files = _read_files(package)
    root = _sample_root(files)
    container = root.find(".//QuotationLines")
    if container is None:  # pragma: no cover - fixture contract
        raise SystemExit("quotation sample has no QuotationLines element")
    for child in list(container):
        if child.tag == "Line":
            container.remove(child)
    _write_sample(files, root)
    return _build_zip(files)


def build() -> dict[str, bytes]:
    """Return ``filename -> deterministic package bytes``."""
    source = SOURCE.read_bytes()
    return {
        "quotation-long-items.ddsp": _long_items(source),
        "quotation-40-rows.ddsp": _forty_rows(source),
        "quotation-empty-lines.ddsp": _empty_lines(source),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail if fixtures are out of date")
    args = parser.parse_args(argv)
    failures = 0
    for name, content in build().items():
        path = FIXTURES / name
        if args.check:
            if not path.exists() or path.read_bytes() != content:
                print(f"out of date: {path.relative_to(ROOT)}")
                failures += 1
        else:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(content)
            print(f"wrote {path.relative_to(ROOT)} ({len(content)} bytes)")
    if args.check and failures:
        print(f"{failures} visual fixture(s) out of date", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
