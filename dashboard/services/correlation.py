"""Request correlation IDs for tracing requests through the system."""
from __future__ import annotations

import logging
import threading
import uuid


# Thread-local storage for correlation ID
_local = threading.local()


def get_correlation_id() -> str:
    """Get the current correlation ID, or generate one if none exists."""
    cid = getattr(_local, "correlation_id", None)
    if cid is None:
        cid = uuid.uuid4().hex[:8]
        _local.correlation_id = cid
    return cid


def set_correlation_id(cid: str) -> None:
    """Set the correlation ID for the current thread."""
    _local.correlation_id = cid


def clear_correlation_id() -> None:
    """Clear the correlation ID for the current thread."""
    _local.correlation_id = None


class CorrelationFilter(logging.Filter):
    """Logging filter that injects correlation_id into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        record.correlation_id = getattr(_local, "correlation_id", "-")
        return True
