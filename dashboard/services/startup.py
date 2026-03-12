"""Startup validation: check env vars and dependencies before serving."""
from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def validate_env() -> None:
    """Warn about missing required .env keys on startup."""
    required = ["DASHBOARD_PIN"]
    optional_groups = {
        "UDM Pro": ["UDM_HOST", "UDM_API_KEY"],
        "Proxmox": ["PROXMOX_HOST", "PROXMOX_TOKEN", "PROXMOX_NODE"],
        "Home Assistant": ["HA_HOST", "HA_TOKEN"],
        "NAS": ["NAS_HOST", "NAS_SSH_USER", "NAS_SSH_PASS"],
    }
    for key in required:
        if not os.environ.get(key):
            logger.warning("Required env var %s is not set", key)
    for group, keys in optional_groups.items():
        missing = [k for k in keys if not os.environ.get(k)]
        if missing:
            logger.info("%s: missing env vars %s (system may not work)", group, missing)


def validate_dependencies() -> None:
    """Check that required packages are importable."""
    deps = {
        "paramiko": "SSH connections",
        "requests": "HTTP API calls",
        "flask": "Web server",
        "flask_socketio": "WebSocket support",
    }
    for pkg, purpose in deps.items():
        try:
            __import__(pkg)
        except ImportError:
            logger.error("Missing dependency: %s (needed for %s)", pkg, purpose)
