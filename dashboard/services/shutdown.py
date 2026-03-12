"""Graceful shutdown: clean up SSH connections, thread pools, etc."""
from __future__ import annotations

import atexit
import logging

logger = logging.getLogger(__name__)


def register_shutdown() -> None:
    """Register cleanup handlers for graceful shutdown."""
    atexit.register(_shutdown)


def _shutdown() -> None:
    """Clean up resources on exit."""
    logger.info("Shutting down — cleaning up resources")

    # Close DNS cache thread pool
    try:
        from blueprints.firewall_bp import dns_cache
        dns_cache._pool.shutdown(wait=False)
    except Exception as e:
        logger.debug("DNS cache cleanup: %s", e)

    # Close NAS SSH pool
    try:
        from services import nas
        from services.ssh_utils import safe_close
        if nas._ssh_client:
            safe_close(nas._ssh_client, timeout=2)
    except Exception as e:
        logger.debug("NAS SSH cleanup: %s", e)

    # Close firewall SSH pool
    try:
        from services import firewall
        from services.ssh_utils import safe_close
        if firewall._lookup_ssh:
            safe_close(firewall._lookup_ssh, timeout=2)
    except Exception as e:
        logger.debug("Firewall SSH cleanup: %s", e)

    # Stop Claude session if active
    try:
        from blueprints.chat_bp import kill_chat_session
        kill_chat_session()
    except Exception as e:
        logger.debug("Claude session cleanup: %s", e)

    logger.info("Shutdown complete")
