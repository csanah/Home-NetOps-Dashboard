"""Shared SSH utilities for keyboard-interactive auth and client creation."""
from __future__ import annotations

import logging
import threading

import paramiko

logger = logging.getLogger(__name__)


def kb_interactive_handler(password: str) -> callable:
    """Return a keyboard-interactive handler that replies with the given password."""
    def handler(title: str, instructions: str, prompt_list: list) -> list[str]:
        return [password] * len(prompt_list)
    return handler


def create_ssh_client(
    host: str,
    username: str,
    password: str,
    port: int = 22,
    use_kb_interactive: bool = False,
    timeout: int = 10,
) -> paramiko.SSHClient:
    """Create and return an authenticated Paramiko SSH client.

    use_kb_interactive: If True, falls back to keyboard-interactive auth
    when standard password auth doesn't fully authenticate (UDM Pro, NAS).
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        hostname=host,
        port=port,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=timeout,
    )
    if use_kb_interactive:
        transport = client.get_transport()
        if transport and not transport.is_authenticated():
            transport.auth_interactive(username, kb_interactive_handler(password))
    return client


def safe_close(client: paramiko.SSHClient, timeout: float = 3.0) -> None:
    """Close an SSH client with a timeout guard.

    SSH close can hang if the remote is unresponsive. This wraps close()
    in a daemon thread so a hung close doesn't block the caller.
    """
    if client is None:
        return

    def _do_close():
        try:
            client.close()
        except Exception as e:
            logger.debug("SSH close error: %s", e)

    t = threading.Thread(target=_do_close, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        logger.warning("SSH close timed out after %.1fs — abandoning", timeout)
