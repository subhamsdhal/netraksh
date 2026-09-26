"""Low-volume, secret-safe process diagnostics for constrained cloud edge runs."""
from __future__ import annotations

import logging
import os
import sys
import time

logger = logging.getLogger(__name__)

_last_active_report = 0.0


def log_runtime_checkpoint(stage: str, *, active: bool = False) -> None:
    """Log RSS and heavyweight-module presence without emitting configuration."""
    global _last_active_report
    if active:
        now = time.monotonic()
        if now - _last_active_report < 10.0:
            return
        _last_active_report = now
    try:
        import psutil
        rss_mb = psutil.Process().memory_info().rss / (1024 * 1024)
    except Exception:
        rss_mb = None
    modules = {name: name in sys.modules for name in ("torch", "torchvision", "ultralytics", "easyocr")}
    logger.info(
        "[RuntimeMemory] stage=%s rss_mb=%s torch=%s torchvision=%s ultralytics=%s easyocr=%s",
        stage,
        f"{rss_mb:.1f}" if rss_mb is not None else "unavailable",
        modules["torch"],
        modules["torchvision"],
        modules["ultralytics"],
        modules["easyocr"],
    )
