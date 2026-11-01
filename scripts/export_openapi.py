#!/usr/bin/env python3
"""Export the FastAPI OpenAPI document to ``docs/openapi.json``."""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main() -> int:
    # Building the app constructs a Store; keep it away from the real data dir.
    os.environ.setdefault("DC_DATA_DIR", tempfile.mkdtemp(prefix="copilot-openapi-"))
    from docentric_copilot.api.app import create_app

    application = create_app()
    document = application.openapi()
    target = ROOT / "docs" / "openapi.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"wrote {target.relative_to(ROOT)} ({len(document['paths'])} paths)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
