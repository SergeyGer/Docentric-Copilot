"""Structured logging with mandatory secret redaction.

The logger never receives raw API keys: adapters pass only provider names and
model identifiers. As defence in depth, every emitted record is scrubbed for
values whose key looks secret and for well-known token prefixes.
"""

from __future__ import annotations

import json
import logging
import re
import sys
from collections.abc import Mapping, Sequence
from typing import Any

_SECRET_KEY = re.compile(
    r"(api[_-]?key|authorization|bearer|secret|password|credential|private[_-]?key"
    r"|(^|[_-])token$|access[_-]?token|refresh[_-]?token)",
    re.IGNORECASE,
)
_SECRET_VALUE = re.compile(
    r"(sk-[A-Za-z0-9]{8,}|sk-ant-[A-Za-z0-9\-_]{8,}|AIza[0-9A-Za-z\-_]{20,}|gh[pousr]_[A-Za-z0-9]{20,})"
)
REDACTED = "***redacted***"


def redact(value: Any, *, key: str | None = None) -> Any:
    """Return a copy of ``value`` with secret-looking material replaced."""
    if key is not None and _SECRET_KEY.search(key):
        return REDACTED
    if isinstance(value, str):
        return _SECRET_VALUE.sub(REDACTED, value)
    if isinstance(value, Mapping):
        return {str(k): redact(v, key=str(k)) for k, v in value.items()}
    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        return [redact(item) for item in value]
    return value


class JsonFormatter(logging.Formatter):
    """One JSON object per line with a stable key order."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": redact(record.getMessage()),
        }
        extra = getattr(record, "context", None)
        if isinstance(extra, Mapping):
            payload["context"] = redact(dict(extra))
        if record.exc_info:
            payload["exception"] = redact(self.formatException(record.exc_info))
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def configure_logging(level: str = "INFO", *, json_output: bool = True) -> None:
    """Configure the root logger once; repeated calls are idempotent."""
    root = logging.getLogger()
    for handler in list(root.handlers):
        root.removeHandler(handler)
    handler = logging.StreamHandler(stream=sys.stderr)
    if json_output:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(levelname)s %(name)s %(message)s"))
    root.addHandler(handler)
    root.setLevel(level.upper())
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


__all__ = ["REDACTED", "configure_logging", "get_logger", "redact"]
