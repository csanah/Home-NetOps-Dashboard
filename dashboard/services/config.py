"""Centralized timeout constants for all services."""
from __future__ import annotations

TIMEOUTS: dict[str, int | tuple[int, int]] = {
    "http_default": (3, 8),
    "http_slow": (3, 15),      # Plex, HA /api/states, Overseerr title resolution
    "http_downloads": (3, 8),
    "ssh_connect": 10,
    "ssh_command": 5,
    "tcp_check": 5,
    "plex": 12,
    "downloads": 8,
    "overseerr": 8,
}
