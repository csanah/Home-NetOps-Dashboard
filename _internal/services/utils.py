"""Shared utility functions for dashboard services."""
from __future__ import annotations


def format_uptime(seconds: float | str) -> str:
    """Format seconds into a human-readable uptime string."""
    seconds = int(float(seconds))
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"
