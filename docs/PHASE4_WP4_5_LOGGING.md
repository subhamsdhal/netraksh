# Phase 4 WP-4.5: Logging Specifications

## Status
**IMPLEMENTED** via `shared/observability/logging.py`.

## RedactingJSONFormatter
Replaces the standard Python output with structured JSON containing strictly isolated operational fields. 

### Required Fields
- `timestamp`: UTC ISO-8601
- `severity`: Standard syslog levels
- `component`: Python module namespace
- `message`: Scrubbed descriptive string

### Context Injected Fields (If Present)
- `correlation_id`: Used to trace edge ingestion through central storage.
- `edge_id`: The originating edge node.
- `camera_id`: The ingestion source.

### Redaction Rules
If a key explicitly matches `(password|passwd|secret|access_token|refresh_token|authorization|jwt|private_key|client_key|database_url|object_storage_secret|rtsp_url|face_embedding|credential)`, its value is replaced with `***REDACTED***`.

RTSP URLs in generic strings undergo regex-based password substitution:
`rtsp://admin:password@10.0.0.1` -> `rtsp://***:***@10.0.0.1`
