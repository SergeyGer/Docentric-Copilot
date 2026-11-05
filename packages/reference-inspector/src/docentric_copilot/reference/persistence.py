"""Persisted Reference report envelope and safe HTML export (v0.11 P1, #29).

The SQLite store keeps only the serialized report/graph/diff envelope; it never
stores the source template bytes. This module owns the public envelope shape and
the safe, self-contained HTML export. Every value is escaped: the export never
injects source-document content as markup or script.
"""

from __future__ import annotations

import html
import json
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .diff import ReferenceDiff
from .graph import ReferenceGraph
from .report import ReferenceReport

PERSISTENCE_VERSION: Literal["1.0"] = "1.0"
RUNTIME_COMPATIBILITY: Literal["not_tested"] = "not_tested"
EXPORT_NOTE: Literal["safe HTML export; no active content from source files"] = (
    "safe HTML export; no active content from source files"
)


class ReferenceReportKind(str, Enum):
    """What a persisted reference report contains."""

    INSPECTION = "inspection"
    GRAPH = "graph"
    DIFF = "diff"


class StoredReferenceReport(BaseModel):
    """The envelope returned by persistence and export endpoints."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    report_version: Literal["1.0"] = PERSISTENCE_VERSION
    runtime_compatibility: Literal["not_tested"] = RUNTIME_COMPATIBILITY
    id: str = Field(min_length=1, max_length=120)
    kind: ReferenceReportKind
    schema_version: str = Field(min_length=1, max_length=40)
    created_at: float
    expires_at: float
    source_name: str = Field(min_length=1, max_length=300)
    source_sha256: str | None = Field(default=None, pattern=r"^[0-9a-f]{64}$")
    report: ReferenceReport | None = None
    graph: ReferenceGraph | None = None
    diff: ReferenceDiff | None = None
    warnings: list[str] = Field(default_factory=list, max_length=100)

    def payload(self) -> dict[str, object]:
        """JSON-safe payload stored in SQLite (report/graph/diff only)."""
        payload: dict[str, object] = {}
        if self.report is not None:
            payload["report"] = self.report.model_dump(mode="json")
        if self.graph is not None:
            payload["graph"] = self.graph.model_dump(mode="json")
        if self.diff is not None:
            payload["diff"] = self.diff.model_dump(mode="json")
        return payload

    def export_json(self, *, indent: int = 2) -> str:
        return (
            json.dumps(
                self.model_dump(mode="json"),
                ensure_ascii=False,
                indent=indent,
                sort_keys=True,
            )
            + "\n"
        )


def _escape(value: object) -> str:
    return html.escape(str(value), quote=True)


def render_stored_report_html(report: StoredReferenceReport) -> str:
    """Render a self-contained, script-free HTML export of one stored report."""
    payload = report.model_dump(mode="json")
    counts = payload.get("report") or {}
    graph_summary = (payload.get("graph") or {}).get("summary") if payload.get("graph") else None
    diff_summary = (payload.get("diff") or {}).get("summary") if payload.get("diff") else None
    warnings = "".join(f"<li>{_escape(item)}</li>" for item in report.warnings) or "<li>None</li>"
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Reference report {_escape(report.id)}</title>
<style>
body {{ font-family: system-ui, sans-serif; margin: 2rem; color: #1f2937; }}
h1 {{ font-size: 1.35rem; }}
h2 {{ font-size: 1.1rem; margin-top: 1.6rem; }}
code {{ font-family: ui-monospace, monospace; word-break: break-all; }}
table {{ border-collapse: collapse; width: 100%; margin-top: .6rem; }}
th, td {{ border: 1px solid #e5e7eb; padding: .3rem .5rem; text-align: left;
          font-size: .85rem; vertical-align: top; }}
th {{ width: 18rem; background: #f9fafb; }}
th.section {{ background: #eef2ff; }}
pre {{ background: #f9fafb; border: 1px solid #e5e7eb; padding: .8rem;
       overflow-x: auto; font-size: .78rem; }}
.note {{ background: #f3f4f6; border-left: 4px solid #6b7280; padding: .7rem 1rem; }}
</style>
</head>
<body>
<h1>Reference report</h1>
<p class="note">Read-only reference evidence. Docentric AX runtime compatibility remains
<strong>{_escape(report.runtime_compatibility)}</strong>. This export contains no active content
from the source files.</p>
<table>
<tr><th>Report ID</th><td><code>{_escape(report.id)}</code></td></tr>
<tr><th>Kind</th><td>{_escape(report.kind.value)}</td></tr>
<tr><th>Schema version</th><td>{_escape(report.schema_version)}</td></tr>
<tr><th>Created at</th><td>{_escape(report.created_at)}</td></tr>
<tr><th>Expires at</th><td>{_escape(report.expires_at)}</td></tr>
<tr><th>Source</th><td>{_escape(report.source_name)}</td></tr>
<tr><th>Source SHA-256</th><td><code>{_escape(report.source_sha256 or "—")}</code></td></tr>
<tr><th>Runtime compatibility</th><td>{_escape(report.runtime_compatibility)}</td></tr>
</table>
<h2>Summary</h2>
<table>
<tr><th>Report metrics</th><td><code>{_escape(json.dumps(counts, sort_keys=True))}</code></td></tr>
<tr><th>Graph summary</th><td><code>{_escape(json.dumps(graph_summary, sort_keys=True) if graph_summary else "—")}</code></td></tr>
<tr><th>Diff summary</th><td><code>{_escape(json.dumps(diff_summary, sort_keys=True) if diff_summary else "—")}</code></td></tr>
</table>
<h2>Warnings</h2>
<ul>{warnings}</ul>
<h2>Full payload (escaped)</h2>
<pre>{_escape(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))}</pre>
<p><small>persistence {_escape(report.report_version)} · safe HTML export</small></p>
</body>
</html>
"""


__all__ = [
    "EXPORT_NOTE",
    "PERSISTENCE_VERSION",
    "RUNTIME_COMPATIBILITY",
    "ReferenceReportKind",
    "StoredReferenceReport",
    "render_stored_report_html",
]
