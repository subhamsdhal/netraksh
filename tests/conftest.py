import os
from pathlib import Path
import pytest

# Keep third-party runtime state inside a disposable, writable repository
# directory. Ultralytics and Matplotlib otherwise target the user's roaming
# profile, which is intentionally unavailable in sandboxed/CI executions and
# makes plain `pytest` fail during collection before any test runs.
_runtime_dir = Path(__file__).resolve().parent.parent / ".pytest-runtime"
_runtime_dir.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("YOLO_CONFIG_DIR", str(_runtime_dir / "ultralytics"))
os.environ.setdefault("MPLCONFIGDIR", str(_runtime_dir / "matplotlib"))
Path(os.environ["YOLO_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
Path(os.environ["MPLCONFIGDIR"]).mkdir(parents=True, exist_ok=True)

# Inject test environment to bypass production secrets validation without
# triggering the 'development' mode which bypasses authentication.
os.environ["ENV"] = "test"

# Also set strong secrets just in case any test expects them
os.environ["SECRET_KEY"] = "deadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"
os.environ["ADMIN_PASSWORD"] = "StrongAdminTest123!"
os.environ["INITIAL_OPERATOR_PASSWORD"] = "StrongOperatorTest123!"
os.environ["INITIAL_AUDITOR_PASSWORD"] = "StrongAuditorTest123!"


@pytest.fixture(autouse=True)
def reset_shared_rate_limiter():
    """Keep the production limiter enabled without leaking counters across tests."""
    try:
        from backend.api.rate_limit import limiter
        limiter._limiter.storage.reset()
    except (AttributeError, ImportError):
        pass
    yield
