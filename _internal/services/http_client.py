from __future__ import annotations

import logging
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logger = logging.getLogger(__name__)
_warned_hosts: set[str] = set()


def create_session(default_timeout: tuple[int, int] = (3, 8)) -> requests.Session:
    """Create a requests.Session with automatic retry and default timeout.

    default_timeout is (connect_timeout, read_timeout) in seconds.
    """
    s = requests.Session()
    retry = Retry(
        total=2,
        backoff_factor=0.5,
        status_forcelist=[502, 503, 504],
        allowed_methods=["GET", "HEAD"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    s.mount("https://", adapter)
    s.mount("http://", adapter)

    # Patch request method to inject default timeout
    _original_request = s.request

    def _request_with_timeout(*args, **kwargs):
        kwargs.setdefault("timeout", default_timeout)
        # Log once per host when SSL verification is disabled
        if kwargs.get("verify") is False:
            url = args[1] if len(args) > 1 else kwargs.get("url", "")
            if url:
                from urllib.parse import urlparse
                host = urlparse(str(url)).hostname or ""
                if host and host not in _warned_hosts:
                    _warned_hosts.add(host)
                    logger.info("SSL verification disabled for %s (self-signed cert)", host)
        return _original_request(*args, **kwargs)

    s.request = _request_with_timeout
    return s


# Shared session for services with identical config (most LAN services).
# Avoids 6 duplicate Session objects with the same retry/timeout settings.
_shared_session: requests.Session | None = None


def get_shared_session() -> requests.Session:
    """Return a module-level shared session (created once, reused by all callers)."""
    global _shared_session
    if _shared_session is None:
        _shared_session = create_session()
    return _shared_session
