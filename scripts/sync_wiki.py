#!/usr/bin/env python3
"""Synchronise ``docs/wiki`` with the GitHub Wiki repository.

``docs/wiki`` is the reviewed source of truth: pages change in the same pull request as
the behaviour they describe. This script publishes them, or pulls remote edits back.

Usage::

    python scripts/sync_wiki.py --push
    python scripts/sync_wiki.py --pull

Authentication reuses ``GITHUB_TOKEN`` or the repository's ``.git-token`` file.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
WIKI = ROOT / "docs" / "wiki"
REPO = "SergeyGer/Docentric-Copilot"


def remote_url() -> str:
    import os

    token = os.environ.get("GITHUB_TOKEN", "").strip()
    token_file = ROOT / ".git-token"
    if not token and token_file.exists():
        token = token_file.read_text().strip()
    if token:
        return f"https://x-access-token:{token}@github.com/{REPO}.wiki.git"
    return f"https://github.com/{REPO}.wiki.git"


def run(*args: str, cwd: Path) -> None:
    result = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if result.returncode != 0:
        print(result.stdout + result.stderr, file=sys.stderr)
        raise SystemExit(f"command failed: {' '.join(args)}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--push", action="store_true", help="publish docs/wiki to the wiki repo")
    group.add_argument("--pull", action="store_true", help="copy remote wiki pages into docs/wiki")
    parser.add_argument("--message", default="Sync wiki pages from docs/wiki")
    args = parser.parse_args(argv)

    with tempfile.TemporaryDirectory() as tmp:
        clone = Path(tmp) / "wiki"
        run("git", "clone", "--depth", "1", remote_url(), str(clone), cwd=Path(tmp))
        if args.pull:
            for page in clone.glob("*.md"):
                shutil.copy2(page, WIKI / page.name)
            print(f"pulled {len(list(clone.glob('*.md')))} pages into docs/wiki")
            return 0

        for page in WIKI.glob("*.md"):
            if page.name == "README.md":
                continue
            shutil.copy2(page, clone / page.name)
        run("git", "add", "-A", cwd=clone)
        if subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=clone).returncode == 0:
            print("wiki already up to date")
            return 0
        run(
            "git",
            "-c",
            "user.name=Docentric Copilot",
            "-c",
            "user.email=copilot@users.noreply.github.com",
            "commit",
            "-m",
            args.message,
            cwd=clone,
        )
        run("git", "push", "origin", "HEAD", cwd=clone)
        print("wiki published")
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
