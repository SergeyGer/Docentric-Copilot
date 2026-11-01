"""SQLite persistence and artifact storage (local MVP).

Design constraints:

* untrusted input never reaches this layer unparsed;
* artifacts expire (TTL) and are removed together with their rows;
* no secret is ever written to the database.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from docentric_copilot.config import Settings, get_settings
from docentric_copilot.errors import ArtifactError, NotFoundError
from docentric_copilot.ids import new_id

_SCHEMA = """
CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    filename TEXT NOT NULL,
    schema_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    schema_json TEXT NOT NULL,
    sample_json TEXT,
    entry_names TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS templates (
    id TEXT PRIMARY KEY,
    source_id TEXT NOT NULL,
    created_at REAL NOT NULL,
    current_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS versions (
    template_id TEXT NOT NULL,
    version INTEGER NOT NULL,
    created_at REAL NOT NULL,
    ir_json TEXT NOT NULL,
    mapping_json TEXT NOT NULL,
    validation_json TEXT NOT NULL,
    provider TEXT NOT NULL,
    model TEXT,
    PRIMARY KEY (template_id, version)
);
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL,
    created_at REAL NOT NULL,
    finished_at REAL,
    request_json TEXT NOT NULL,
    result_json TEXT,
    error_json TEXT
);
CREATE TABLE IF NOT EXISTS artifacts (
    id TEXT PRIMARY KEY,
    job_id TEXT,
    template_id TEXT,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    media_type TEXT NOT NULL,
    path TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    digest TEXT NOT NULL,
    created_at REAL NOT NULL,
    expires_at REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_artifacts_expires ON artifacts(expires_at);
CREATE INDEX IF NOT EXISTS idx_versions_template ON versions(template_id, version);
"""


@dataclass(frozen=True)
class SourceRecord:
    id: str
    filename: str
    schema_id: str
    created_at: float
    schema_json: str
    sample_json: str | None
    entry_names: list[str]

    def schema_dict(self) -> dict[str, Any]:
        return json.loads(self.schema_json)

    def sample_dict(self) -> dict[str, Any] | None:
        return json.loads(self.sample_json) if self.sample_json else None


@dataclass(frozen=True)
class ArtifactRecord:
    id: str
    kind: str
    filename: str
    media_type: str
    path: Path
    size_bytes: int
    digest: str
    created_at: float
    expires_at: float
    template_id: str | None = None
    job_id: str | None = None

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at


@dataclass(frozen=True)
class JobRecord:
    id: str
    kind: str
    status: str
    created_at: float
    finished_at: float | None
    request: dict[str, Any]
    result: dict[str, Any] | None
    error: dict[str, Any] | None

    @property
    def duration_ms(self) -> int | None:
        if self.finished_at is None:
            return None
        return int((self.finished_at - self.created_at) * 1_000)


@dataclass(frozen=True)
class VersionRecord:
    template_id: str
    version: int
    created_at: float
    ir_json: str
    mapping_json: str
    validation_json: str
    provider: str
    model: str | None

    def ir(self) -> dict[str, Any]:
        return json.loads(self.ir_json)

    def mapping(self) -> dict[str, Any]:
        return json.loads(self.mapping_json)

    def validation(self) -> dict[str, Any]:
        return json.loads(self.validation_json)


class Store:
    """Thin, explicit persistence layer. One process, one SQLite file."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()
        self._data_dir = Path(self._settings.data_dir)
        self._artifact_dir = self._data_dir / "artifacts"
        self._data_dir.mkdir(parents=True, exist_ok=True)
        self._artifact_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._connection = sqlite3.connect(
            self._data_dir / "copilot.db", check_same_thread=False, isolation_level=None
        )
        self._connection.row_factory = sqlite3.Row
        with self._lock:
            self._connection.executescript(_SCHEMA)

    # ------------------------------------------------------------------ close
    def close(self) -> None:
        with self._lock:
            self._connection.close()

    # ---------------------------------------------------------------- sources
    def create_source(
        self,
        *,
        filename: str,
        schema_id: str,
        schema: dict[str, Any],
        sample: dict[str, Any] | None,
        entry_names: list[str],
    ) -> SourceRecord:
        source_id = new_id("src")
        created = time.time()
        record = SourceRecord(
            id=source_id,
            filename=filename[:200],
            schema_id=schema_id[:120],
            created_at=created,
            schema_json=json.dumps(schema, ensure_ascii=False, sort_keys=True),
            sample_json=json.dumps(sample, ensure_ascii=False, sort_keys=True) if sample else None,
            entry_names=entry_names,
        )
        with self._lock:
            self._connection.execute(
                "INSERT INTO sources (id, filename, schema_id, created_at, schema_json, sample_json, "
                "entry_names) VALUES (?,?,?,?,?,?,?)",
                (
                    record.id,
                    record.filename,
                    record.schema_id,
                    record.created_at,
                    record.schema_json,
                    record.sample_json,
                    json.dumps(record.entry_names),
                ),
            )
        return record

    def get_source(self, source_id: str) -> SourceRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
        if row is None:
            raise NotFoundError("Data source not found", details={"source_id": source_id})
        return SourceRecord(
            id=row["id"],
            filename=row["filename"],
            schema_id=row["schema_id"],
            created_at=row["created_at"],
            schema_json=row["schema_json"],
            sample_json=row["sample_json"],
            entry_names=json.loads(row["entry_names"]),
        )

    # ---------------------------------------------------------------- jobs
    def create_job(self, kind: str, request: dict[str, Any]) -> str:
        job_id = new_id("job")
        with self._lock:
            self._connection.execute(
                "INSERT INTO jobs (id, kind, status, created_at, request_json) VALUES (?,?,?,?,?)",
                (job_id, kind, "running", time.time(), json.dumps(request, ensure_ascii=False)),
            )
        return job_id

    def finish_job(self, job_id: str, result: dict[str, Any]) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET status = 'completed', finished_at = ?, result_json = ? WHERE id = ?",
                (time.time(), json.dumps(result, ensure_ascii=False), job_id),
            )

    def fail_job(self, job_id: str, error: dict[str, Any]) -> None:
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET status = 'failed', finished_at = ?, error_json = ? WHERE id = ?",
                (time.time(), json.dumps(error, ensure_ascii=False), job_id),
            )

    def get_job(self, job_id: str) -> JobRecord:
        with self._lock:
            row = self._connection.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if row is None:
            raise NotFoundError("Job not found", details={"job_id": job_id})
        return JobRecord(
            id=row["id"],
            kind=row["kind"],
            status=row["status"],
            created_at=row["created_at"],
            finished_at=row["finished_at"],
            request=json.loads(row["request_json"]),
            result=json.loads(row["result_json"]) if row["result_json"] else None,
            error=json.loads(row["error_json"]) if row["error_json"] else None,
        )

    # ------------------------------------------------------------- templates
    def create_template(self, source_id: str) -> tuple[str, int]:
        template_id = new_id("tpl")
        with self._lock:
            self._connection.execute(
                "INSERT INTO templates (id, source_id, created_at, current_version) VALUES (?,?,?,?)",
                (template_id, source_id, time.time(), 0),
            )
        return template_id, 0

    def add_version(
        self,
        template_id: str,
        *,
        ir: dict[str, Any],
        mapping: dict[str, Any],
        validation: dict[str, Any],
        provider: str,
        model: str | None,
    ) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT current_version FROM templates WHERE id = ?", (template_id,)
            ).fetchone()
            if row is None:
                raise NotFoundError("Template not found", details={"template_id": template_id})
            version = int(row["current_version"]) + 1
            self._connection.execute(
                "INSERT INTO versions (template_id, version, created_at, ir_json, mapping_json, "
                "validation_json, provider, model) VALUES (?,?,?,?,?,?,?,?)",
                (
                    template_id,
                    version,
                    time.time(),
                    json.dumps(ir, ensure_ascii=False, sort_keys=True),
                    json.dumps(mapping, ensure_ascii=False, sort_keys=True),
                    json.dumps(validation, ensure_ascii=False, sort_keys=True),
                    provider,
                    model,
                ),
            )
            self._connection.execute(
                "UPDATE templates SET current_version = ? WHERE id = ?", (version, template_id)
            )
        return version

    def get_version(self, template_id: str, version: int | None = None) -> VersionRecord:
        with self._lock:
            if version is None:
                row = self._connection.execute(
                    "SELECT v.* FROM versions v JOIN templates t ON t.id = v.template_id "
                    "WHERE v.template_id = ? AND v.version = t.current_version",
                    (template_id,),
                ).fetchone()
            else:
                row = self._connection.execute(
                    "SELECT * FROM versions WHERE template_id = ? AND version = ?",
                    (template_id, version),
                ).fetchone()
        if row is None:
            raise NotFoundError(
                "Template version not found",
                details={"template_id": template_id, "version": version},
            )
        return VersionRecord(
            template_id=row["template_id"],
            version=row["version"],
            created_at=row["created_at"],
            ir_json=row["ir_json"],
            mapping_json=row["mapping_json"],
            validation_json=row["validation_json"],
            provider=row["provider"],
            model=row["model"],
        )

    def list_versions(self, template_id: str) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._connection.execute(
                "SELECT version, created_at, provider, model FROM versions WHERE template_id = ? "
                "ORDER BY version ASC",
                (template_id,),
            ).fetchall()
        return [
            {
                "version": row["version"],
                "created_at": row["created_at"],
                "provider": row["provider"],
                "model": row["model"],
            }
            for row in rows
        ]

    # ------------------------------------------------------------- artifacts
    def save_artifact(
        self,
        *,
        kind: str,
        filename: str,
        media_type: str,
        content: bytes,
        digest: str,
        job_id: str | None = None,
        template_id: str | None = None,
    ) -> ArtifactRecord:
        artifact_id = new_id("art")
        extension = Path(filename).suffix[:10] or ".bin"
        path = self._artifact_dir / f"{artifact_id}{extension}"
        path.write_bytes(content)
        created = time.time()
        record = ArtifactRecord(
            id=artifact_id,
            kind=kind[:40],
            filename=filename[:120],
            media_type=media_type[:100],
            path=path,
            size_bytes=len(content),
            digest=digest,
            created_at=created,
            expires_at=created + self._settings.artifact_ttl_seconds,
            template_id=template_id,
            job_id=job_id,
        )
        with self._lock:
            self._connection.execute(
                "INSERT INTO artifacts (id, job_id, template_id, kind, filename, media_type, path, "
                "size_bytes, digest, created_at, expires_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (
                    record.id,
                    record.job_id,
                    record.template_id,
                    record.kind,
                    record.filename,
                    record.media_type,
                    str(record.path),
                    record.size_bytes,
                    record.digest,
                    record.created_at,
                    record.expires_at,
                ),
            )
        return record

    def get_artifact(self, artifact_id: str) -> ArtifactRecord:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
        if row is None:
            raise ArtifactError(
                "Artifact not found or expired", details={"artifact_id": artifact_id}
            )
        record = ArtifactRecord(
            id=row["id"],
            kind=row["kind"],
            filename=row["filename"],
            media_type=row["media_type"],
            path=Path(row["path"]),
            size_bytes=row["size_bytes"],
            digest=row["digest"],
            created_at=row["created_at"],
            expires_at=row["expires_at"],
            template_id=row["template_id"],
            job_id=row["job_id"],
        )
        if record.expired or not record.path.exists():
            self.delete_artifact(record.id)
            raise ArtifactError("Artifact has expired", details={"artifact_id": artifact_id})
        return record

    def delete_artifact(self, artifact_id: str) -> None:
        with self._lock:
            row = self._connection.execute(
                "SELECT path FROM artifacts WHERE id = ?", (artifact_id,)
            ).fetchone()
            if row is not None:
                Path(row["path"]).unlink(missing_ok=True)
                self._connection.execute("DELETE FROM artifacts WHERE id = ?", (artifact_id,))

    # ------------------------------------------------------------- retention
    def purge_expired(self, now: float | None = None) -> dict[str, int]:
        """Delete expired artifacts and sources. Returns counts for telemetry."""
        reference = time.time() if now is None else now
        removed_artifacts = 0
        with self._lock:
            rows = self._connection.execute(
                "SELECT id, path FROM artifacts WHERE expires_at < ?", (reference,)
            ).fetchall()
            for row in rows:
                Path(row["path"]).unlink(missing_ok=True)
                self._connection.execute("DELETE FROM artifacts WHERE id = ?", (row["id"],))
                removed_artifacts += 1
            source_rows = self._connection.execute(
                "SELECT id FROM sources WHERE created_at < ?",
                (reference - self._settings.artifact_ttl_seconds,),
            ).fetchall()
            for row in source_rows:
                self._connection.execute("DELETE FROM sources WHERE id = ?", (row["id"],))
        return {"artifacts": removed_artifacts, "sources": len(source_rows)}


__all__ = ["ArtifactRecord", "JobRecord", "SourceRecord", "Store", "VersionRecord"]
