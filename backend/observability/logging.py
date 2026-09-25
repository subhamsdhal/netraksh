"""
NETRAKSH — Structured JSON logging + request correlation.

Design:
  - Uses Python's stdlib `logging` only (no OpenTelemetry, no third-party logger).
  - JSON formatter emits a single-line JSON object per log record.
  - Correlation ID is stored in a contextvars.ContextVar and injected into every
    log record by the formatter.
  - The X-Request-ID middleware (in middleware.py) sets the correlation ID per request.

Fields emitted in every log record:
  timestamp  — ISO 8601 UTC, e.g. "2024-01-15T12:34:56.789Z"
  level      — "INFO", "ERROR", etc.
  logger     — logger name, e.g. "backend.api.events"
  message    — log message
  request_id — UUID or "-" if no request context
  (extra fields can be added via logger.info(..., extra={...}))

Secret sanitization:
  The formatter strips any key matching SECRET_KEYS before emitting.
  This prevents accidental logging of passwords, tokens, or keys that
  happen to be passed as extra= kwargs.
"""
import contextvars
import json
import logging
import re
import time
from typing import Optional

# ─── Request correlation context ─────────────────────────────────────────────
# Set per-request by the ASGI middleware. Falls back to "-" outside request context.
_correlation_id: contextvars.ContextVar[str] = contextvars.ContextVar(
    "correlation_id", default="-"
)


def get_correlation_id() -> str:
    return _correlation_id.get()


def set_correlation_id(value: str) -> contextvars.Token:
    return _correlation_id.set(value)


def reset_correlation_id(token: contextvars.Token) -> None:
    _correlation_id.reset(token)


# ─── Secret sanitization ─────────────────────────────────────────────────────
# Any extra key whose name matches this pattern is replaced with "***REDACTED***"
# in the JSON output. This is a defence-in-depth measure, NOT a substitute for
# not passing secrets to loggers in the first place.
_SECRET_KEY_PATTERN = re.compile(
    r"(password|secret|token|key|credential|auth|api_key|access_key)",
    re.IGNORECASE,
)

_REDACTED = "***REDACTED***"


def _sanitize(record_dict: dict) -> dict:
    """Return a copy of record_dict with secret fields replaced."""
    result = {}
    for k, v in record_dict.items():
        if _SECRET_KEY_PATTERN.search(k):
            result[k] = _REDACTED
        else:
            result[k] = v
    return result


# ─── JSON Formatter ────────────────────────────────────────────────────────────


class JSONFormatter(logging.Formatter):
    """
    Formats log records as single-line JSON objects.

    Usage in logging.config:
        handler.setFormatter(JSONFormatter())
    """

    # Standard LogRecord attributes to exclude from the JSON "extra" block
    _RESERVED_ATTRS = frozenset({
        "args", "asctime", "created", "exc_info", "exc_text", "filename",
        "funcName", "id", "levelname", "levelno", "lineno", "module",
        "msecs", "message", "msg", "name", "pathname", "process",
        "processName", "relativeCreated", "stack_info", "thread",
        "threadName",
    })

    def format(self, record: logging.LogRecord) -> str:
        # Format exception if present
        if record.exc_info and not record.exc_text:
            record.exc_text = self.formatException(record.exc_info)

        # Collect extra fields (anything not in LogRecord's standard attrs)
        extra = {}
        for key, value in record.__dict__.items():
            if key not in self._RESERVED_ATTRS:
                extra[key] = value

        # Sanitize secrets from extras
        extra = _sanitize(extra)

        log_object: dict = {
            "timestamp": self._utcnow_iso(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": get_correlation_id(),
        }
        if extra:
            log_object["extra"] = extra
        if record.exc_text:
            log_object["exception"] = record.exc_text

        return json.dumps(log_object, default=str)

    @staticmethod
    def _utcnow_iso() -> str:
        # time.gmtime() avoids the deprecated datetime.utcnow()
        t = time.gmtime()
        ms = int((time.time() % 1) * 1000)
        return f"{t.tm_year:04d}-{t.tm_mon:02d}-{t.tm_mday:02d}T" \
               f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}.{ms:03d}Z"


# ─── Setup helper ─────────────────────────────────────────────────────────────


def configure_json_logging(level: str = "INFO") -> None:
    """
    Replace application handlers on the root logger with a JSON handler.
    Call once at application startup (main.py lifespan).
    """
    import sys

    root = logging.getLogger()
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JSONFormatter())

    # Keep pytest's capture handler if present. Clearing it during the app
    # lifespan makes operational errors invisible to the test runner.
    for existing in list(root.handlers):
        if not existing.__class__.__module__.startswith("_pytest."):
            root.removeHandler(existing)
    root.addHandler(handler)
