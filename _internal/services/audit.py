"""Audit logging: security-relevant actions logged to a separate file."""
from __future__ import annotations

import logging
import logging.handlers
from datetime import datetime

from runtime import LOG_DIR

# Separate audit logger with its own file handler
_audit_logger = logging.getLogger("dashboard.audit")
_audit_logger.setLevel(logging.INFO)
_audit_logger.propagate = False

_audit_file = LOG_DIR / "audit.log"
_audit_handler = logging.handlers.RotatingFileHandler(
    _audit_file, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8"
)
_audit_handler.setFormatter(
    logging.Formatter("%(asctime)s [AUDIT] %(message)s")
)
_audit_logger.addHandler(_audit_handler)


def log_action(action: str, user_ip: str = "", details: str = "") -> None:
    """Log a security-relevant action to the audit log.

    Actions: login_success, login_failure, logout, settings_save,
    connection_test, export, firewall_lookup, chat_message.
    """
    parts = [action]
    if user_ip:
        parts.append(f"ip={user_ip}")
    if details:
        parts.append(details)
    _audit_logger.info(" | ".join(parts))
