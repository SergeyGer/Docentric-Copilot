#!/usr/bin/env python3
"""Verify documentation links, ADR structure and wiki sidebar coverage.

Checks
------
* every relative link in ``docs/**/*.md`` and ``docs/wiki/*.md`` resolves to a file
* in-page anchors resolve against the headings of the target page
* every ADR has Status / Context / Decision / Consequences
* every ADR file is referenced from the ADR index
* every wiki page is listed in ``docs/wiki/_Sidebar.md``

Usage: ``python scripts/check_docs_links.py``
"""

from __future__ import annotations

import re
import sys
from pathlib import Path
from urllib.parse import unquote

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
LINK = re.compile(r"(?<!!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.MULTILINE)
ADR_REQUIRED = ("Status", "Context", "Decision", "Consequences")


def slug(text: str) -> str:
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)
    text = re.sub(r"[^\w\s-]", "", text).strip().lower()
    # GitHub keeps one hyphen per space; an em dash therefore leaves two.
    return text.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    return {slug(match.group(2)) for match in HEADING.finditer(path.read_text(encoding="utf-8"))}


def check_links(path: Path, failures: list[str]) -> None:
    for raw in LINK.findall(path.read_text(encoding="utf-8")):
        target = raw.strip()
        if target.startswith(("http://", "https://", "mailto:")):
            continue
        if target.startswith("#"):
            if target[1:] and slug(target[1:]) not in anchors(path):
                failures.append(f"{path.relative_to(ROOT)}: missing anchor {target}")
            continue
        file_part, _, anchor = target.partition("#")
        resolved = (path.parent / unquote(file_part)).resolve()
        if file_part.startswith("/"):
            resolved = (ROOT / file_part.lstrip("/")).resolve()
        if not resolved.exists() and resolved.suffix == "":
            # GitHub wiki pages are linked without an extension.
            resolved = resolved.with_suffix(".md")
        if not resolved.exists():
            failures.append(f"{path.relative_to(ROOT)}: missing target {target}")
            continue
        if anchor and resolved.suffix == ".md" and slug(anchor) not in anchors(resolved):
            failures.append(f"{path.relative_to(ROOT)}: missing anchor {target}")


def check_adrs(failures: list[str]) -> None:
    adrs = sorted((DOCS / "adr").glob("[0-9][0-9][0-9][0-9]-*.md"))
    if not adrs:
        failures.append("docs/adr: no ADRs found")
        return
    index_candidates = [DOCS / "adr" / "README.md", DOCS / "ARCHITECTURE.md"]
    index_text = ""
    for candidate in index_candidates:
        if candidate.exists():
            index_text += candidate.read_text(encoding="utf-8")
    for adr in adrs:
        body = adr.read_text(encoding="utf-8")
        headings = {match.group(2).strip().lower() for match in HEADING.finditer(body)}
        fields = {
            match.group(1).strip().lower()
            for match in re.finditer(r"^\*\*([^*]+):\*\*", body, re.M)
        }
        fields |= {
            match.group(1).strip().lower()
            for match in re.finditer(r"^\|\s*([A-Za-z ]+?)\s*\|", body, re.M)
        }
        for required in ADR_REQUIRED:
            if required.lower() not in headings and required.lower() not in fields:
                failures.append(f"{adr.relative_to(ROOT)}: missing '{required}' section")
        if adr.name not in index_text and adr.stem not in index_text:
            failures.append(f"{adr.relative_to(ROOT)}: not listed in the ADR index")


def check_wiki(failures: list[str]) -> None:
    wiki = DOCS / "wiki"
    pages = sorted(
        page
        for page in wiki.glob("*.md")
        if not page.name.startswith("_") and page.name != "README.md"
    )
    sidebar = wiki / "_Sidebar.md"
    sidebar_text = sidebar.read_text(encoding="utf-8") if sidebar.exists() else ""
    if not sidebar_text:
        failures.append("docs/wiki/_Sidebar.md is missing")
    for page in pages:
        check_links(page, failures)
        if page.stem not in sidebar_text:
            failures.append(f"{page.relative_to(ROOT)}: not listed in _Sidebar.md")
    for asset in re.findall(
        r"!\[[^\]]*\]\(([^)\s]+)\)", "".join(p.read_text(encoding="utf-8") for p in pages)
    ):
        if asset.startswith(("http://", "https://")):
            continue
        if not (wiki / asset).exists():
            failures.append(f"docs/wiki: missing image {asset}")


def main() -> int:
    failures: list[str] = []
    for path in sorted(DOCS.rglob("*.md")):
        if path.parent.name == "wiki":
            continue
        check_links(path, failures)
    check_adrs(failures)
    check_wiki(failures)
    if failures:
        print("documentation checks failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        return 1
    print("documentation checks passed: links, ADR structure, wiki sidebar")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
