"""
NETRAKSH — Centralized rate-limiting setup using slowapi.

WHY slowapi:
  - Zero additional infrastructure (no Redis needed for this use-case)
  - Uses in-process memory store for demo; swap to RedisStore for production
  - Integrates natively with FastAPI/Starlette middleware

SECURITY RATIONALE:
  - Ingest endpoint (POST /events) is the highest-risk surface: a rogue or
    compromised edge device could flood the database. Rate limiting is the
    first line of defence before authentication and payload validation.
  - Dashboard API endpoints (GET /events, POST /events/{id}/verify) are
    rate-limited to prevent scraping and brute-force replay attacks.
  - Use the `limiter` dependency in routers via @limiter.limit("N/minute").

DEPLOYMENT NOTE:
  In a multi-process deployment (Gunicorn + multiple workers), the in-memory
  store does NOT share state across workers. For true rate limiting at scale,
  replace MemoryStore with:
    from slowapi.util import get_remote_address
    from slowapi import Limiter
    limiter = Limiter(key_func=get_remote_address,
                      storage_uri="redis://redis:6379")
"""
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded

# Key function: rate-limit by caller's IP address.
# For edge devices behind a NAT, also consider keying by JWT sub (device ID).
limiter = Limiter(key_func=get_remote_address)

__all__ = ["limiter", "RateLimitExceeded", "_rate_limit_exceeded_handler"]
