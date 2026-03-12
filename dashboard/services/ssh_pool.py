"""Generalized SSH connection pool with keepalive and metrics."""
from __future__ import annotations

import logging
import threading
from typing import Callable

import paramiko

from .ssh_utils import safe_close
from .metrics import metrics

logger = logging.getLogger(__name__)


class SSHPool:
    """Manages a single persistent SSH connection with automatic reconnection.

    Encapsulates the get-or-create-with-keepalive pattern used by NAS and
    firewall services, adding metrics tracking for connection reuse/reconnection.
    """

    def __init__(self, name: str, create_fn: Callable[[], paramiko.SSHClient]) -> None:
        self._name = name
        self._create_fn = create_fn
        self._client: paramiko.SSHClient | None = None
        self._lock = threading.Lock()

    def get(self) -> paramiko.SSHClient:
        """Get or create a persistent SSH client."""
        with self._lock:
            if self._client is not None:
                try:
                    transport = self._client.get_transport()
                    if transport and transport.is_active():
                        transport.send_ignore()
                        metrics.increment(f"ssh_pool.{self._name}.reuse")
                        return self._client
                except Exception as e:
                    logger.debug("SSH keepalive check failed for %s: %s", self._name, e)
                    safe_close(self._client, timeout=2)
                    self._client = None

            self._client = self._create_fn()
            metrics.increment(f"ssh_pool.{self._name}.connect")
            return self._client

    def close(self) -> None:
        """Close the pooled connection."""
        with self._lock:
            if self._client is not None:
                safe_close(self._client, timeout=2)
                self._client = None

    def invalidate(self) -> None:
        """Mark the current connection as invalid (e.g., after an error)."""
        with self._lock:
            safe_close(self._client, timeout=2)
            self._client = None
            metrics.increment(f"ssh_pool.{self._name}.invalidate")
