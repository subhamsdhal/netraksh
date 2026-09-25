"""
NETRAKSH — ASGI observability middleware.

Two middlewares:

1. RequestCorrelationMiddleware
   - Reads X-Request-ID from the incoming request (or generates a UUID4).
   - Sets the correlation ID in the contextvars store.
   - Adds X-Request-ID to the response headers.
   - This makes the ID appear in all log records for that request.

2. PrometheusMiddleware
   - Wraps every HTTP request to record:
       * netraksh_http_requests_total{method, status_class, endpoint_group}
       * netraksh_http_request_duration_seconds{method, endpoint_group}
   - MUST be added AFTER RequestCorrelationMiddleware in the stack.
   - Skips the /metrics endpoint itself to avoid counting Prometheus scrapes.

Usage in main.py:
    app.add_middleware(PrometheusMiddleware)
    app.add_middleware(RequestCorrelationMiddleware)
"""
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from backend.observability.logging import set_correlation_id, reset_correlation_id
from backend.observability.metrics import (
    HTTP_REQUESTS_TOTAL,
    HTTP_REQUEST_DURATION,
    classify_endpoint,
)


class RequestCorrelationMiddleware(BaseHTTPMiddleware):
    """
    Reads or generates a request correlation ID and injects it into the log context.
    Adds X-Request-ID to all responses.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # Accept an externally-provided trace ID (from a load balancer or edge proxy).
        # Validate basic format: non-empty, printable ASCII, length ≤ 128.
        incoming = request.headers.get("X-Request-ID", "")
        if incoming and incoming.isprintable() and len(incoming) <= 128:
            correlation_id = incoming
        else:
            correlation_id = str(uuid.uuid4())

        token = set_correlation_id(correlation_id)
        try:
            response = await call_next(request)
        finally:
            reset_correlation_id(token)

        response.headers["X-Request-ID"] = correlation_id
        return response


class PrometheusMiddleware(BaseHTTPMiddleware):
    """
    Records HTTP request count and duration in Prometheus metrics.
    Skips /metrics path to avoid self-counting.
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        path = request.url.path

        # Skip Prometheus scrape endpoint — don't record metrics about metrics
        if path == "/metrics":
            return await call_next(request)

        method = request.method
        endpoint_group = classify_endpoint(path)

        start = time.perf_counter()
        response = await call_next(request)
        duration = time.perf_counter() - start

        status_code = response.status_code
        status_class = f"{status_code // 100}xx"

        HTTP_REQUESTS_TOTAL.labels(
            method=method,
            status_class=status_class,
            endpoint_group=endpoint_group,
        ).inc()

        HTTP_REQUEST_DURATION.labels(
            method=method,
            endpoint_group=endpoint_group,
        ).observe(duration)

        return response
