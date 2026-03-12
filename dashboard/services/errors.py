"""Structured error types for dashboard services."""
from __future__ import annotations

import uuid


class DashboardError(Exception):
    """Base error for all dashboard service failures."""

    def __init__(self, message: str, system: str = "", operation: str = "") -> None:
        self.system = system
        self.operation = operation
        self.correlation_id = uuid.uuid4().hex[:8]
        super().__init__(message)


class ServiceConnectionError(DashboardError):
    """SSH or HTTP connection failure."""
    pass


class ServiceAuthError(DashboardError):
    """Authentication failure (bad token, wrong password)."""
    pass


class ServiceTimeoutError(DashboardError):
    """Operation timed out."""
    pass


class ConfigurationError(DashboardError):
    """Missing or invalid .env configuration."""
    pass


class SSHCloseError(DashboardError):
    """SSH client cleanup failure."""
    pass
