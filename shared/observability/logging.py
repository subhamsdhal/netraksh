import os
import re
import json
import logging
from contextvars import ContextVar
import datetime

# Correlation ID and Edge/Camera context variables
correlation_id_var = ContextVar("correlation_id", default=None)
edge_id_var = ContextVar("edge_id", default=None)
camera_id_var = ContextVar("camera_id", default=None)

# Patterns for redaction
_SENSITIVE_KEYS = re.compile(
    r"(password|passwd|secret|access_token|refresh_token|authorization|jwt|private_key|client_key|database_url|object_storage_secret|rtsp_url|face_embedding|credential)",
    re.IGNORECASE
)

# Sanitize RTSP URLs specifically: rtsp://user:pass@host -> rtsp://***:***@host
_RTSP_CREDENTIAL_PATTERN = re.compile(r"(rtsp://)([^:]+):([^@]+)(@.*)", re.IGNORECASE)

class RedactingJSONFormatter(logging.Formatter):
    """
    JSON formatter that injects correlation context and recursively redacts sensitive fields.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def _redact_value(self, key: str, value: any) -> any:
        if isinstance(value, str):
            if key.lower() == "rtsp_url":
                return _RTSP_CREDENTIAL_PATTERN.sub(r"\1***:***\4", value)
            if _SENSITIVE_KEYS.search(key):
                return "***REDACTED***"
            if "rtsp://" in value.lower():
                return _RTSP_CREDENTIAL_PATTERN.sub(r"\1***:***\4", value)
        if isinstance(value, dict):
            return self._redact_dict(value)
        if isinstance(value, list):
            return [self._redact_value(key, v) for v in value]
        
        # Catch-all key match just in case
        if isinstance(key, str) and _SENSITIVE_KEYS.search(key):
             return "***REDACTED***"
             
        return value

    def _redact_dict(self, d: dict) -> dict:
        return {k: self._redact_value(str(k), v) for k, v in d.items()}

    def format(self, record: logging.LogRecord) -> str:
        # Avoid failure on formatting errors
        try:
            message = record.getMessage()
            # Redact raw messages just in case a URL or secret was logged as string
            message = _RTSP_CREDENTIAL_PATTERN.sub(r"\1***:***\4", message)
        except Exception:
            message = "Unformattable log message"

        log_data = {
            "timestamp": datetime.datetime.fromtimestamp(record.created, tz=datetime.timezone.utc).isoformat(),
            "severity": record.levelname,
            "component": record.name,
            "message": message,
        }

        if hasattr(record, "event_type"):
            log_data["event_type"] = record.event_type
        if hasattr(record, "result"):
            log_data["result"] = record.result
        if hasattr(record, "duration_ms"):
            log_data["duration_ms"] = record.duration_ms

        cid = correlation_id_var.get()
        if cid: log_data["correlation_id"] = cid
        
        eid = edge_id_var.get()
        if eid: log_data["edge_id"] = eid
        
        cam = camera_id_var.get()
        if cam: log_data["camera_id"] = cam

        # Redact anything attached to the record's __dict__ (extra vars) safely
        extra = {}
        for k, v in record.__dict__.items():
            if k not in ["args", "asctime", "created", "exc_info", "exc_text", "filename", "funcName", "levelname", "levelno", "lineno", "module", "msecs", "message", "msg", "name", "pathname", "process", "processName", "relativeCreated", "stack_info", "thread", "threadName", "taskName"]:
                # Only include primitive or easily serializable types
                if isinstance(v, (str, int, float, bool, dict, list, type(None))):
                    extra[k] = v
        
        if extra:
            log_data.update(self._redact_dict(extra))

        try:
            return json.dumps(log_data)
        except Exception:
            # Absolute fallback to ensure pipeline continues
            return json.dumps({"severity": record.levelname, "message": "Log serialization failed"})

def setup_json_logging(level=logging.INFO):
    """Sets up the root logger to use the RedactingJSONFormatter."""
    root = logging.getLogger()
    # Clear existing handlers
    if root.hasHandlers():
        root.handlers.clear()
        
    handler = logging.StreamHandler()
    handler.setFormatter(RedactingJSONFormatter())
    root.addHandler(handler)
    root.setLevel(level)
