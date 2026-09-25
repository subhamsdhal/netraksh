"""
NETRAKSH — Observability package.

Components:
  metrics.py   — prometheus_client metrics registry (bounded cardinality)
  logging.py   — JSON structured log formatter + correlation ID via contextvars
  middleware.py — ASGI request correlation + Prometheus HTTP instrumentation
"""
