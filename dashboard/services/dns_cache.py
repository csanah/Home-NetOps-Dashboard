from __future__ import annotations

import socket
import time
import threading
import ipaddress
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

from .metrics import metrics


class DNSCache:
    """Async reverse DNS resolver with in-memory LRU cache."""

    def __init__(self, max_entries: int = 2000, success_ttl: int = 600, failure_ttl: int = 300) -> None:
        self._cache: OrderedDict[str, tuple[str | None, float]] = OrderedDict()
        self._lock = threading.Lock()
        # Dedup set: prevents duplicate thread pool submissions for the same IP
        # while a resolve is already in flight
        self._pending: set[str] = set()
        self._max = max_entries
        self._success_ttl = success_ttl
        self._failure_ttl = failure_ttl
        self._pool = ThreadPoolExecutor(max_workers=4)

    @staticmethod
    def is_external(ip: str) -> bool:
        """Return True if IP is not in a private/reserved range."""
        try:
            addr = ipaddress.ip_address(ip)
            return not (addr.is_private or addr.is_loopback
                        or addr.is_link_local or addr.is_multicast)
        except ValueError:
            return False

    def lookup(self, ip: str, callback: Callable[[str, str], None]) -> None:
        """Look up hostname for ip. Calls callback(ip, hostname) when done.
        Returns cached result immediately if available, otherwise schedules async lookup.
        """
        now = time.time()

        with self._lock:
            # Check cache
            if ip in self._cache:
                hostname, expires = self._cache[ip]
                if now < expires:
                    # LRU touch: move to end so least-recently-used entries
                    # stay at the front and get evicted first
                    self._cache.move_to_end(ip)
                    metrics.increment("dns_cache.hit")
                    if hostname:
                        callback(ip, hostname)
                    # Negative cache: hostname is None for failed lookups, so we
                    # return early without callback to avoid re-resolving bad IPs
                    return
            metrics.increment("dns_cache.miss")

            # Skip if already pending
            if ip in self._pending:
                return

            self._pending.add(ip)
        self._pool.submit(self._resolve, ip, callback)

    def _resolve(self, ip: str, callback: Callable[[str, str], None]) -> None:
        """Perform blocking reverse DNS and cache the result (or cache None on failure)."""
        try:
            hostname, _, _ = socket.gethostbyaddr(ip)
            self._store(ip, hostname)
            callback(ip, hostname)
        except (socket.herror, socket.gaierror, OSError):
            # Negative cache: store None so we don't retry unresolvable IPs
            # until the failure TTL expires
            self._store(ip, None)
        finally:
            self._pending.discard(ip)

    def _store(self, ip: str, hostname: str | None) -> None:
        """Insert or update a cache entry; evicts oldest entry if at capacity."""
        ttl = self._success_ttl if hostname else self._failure_ttl
        with self._lock:
            # Evict LRU if at capacity — O(1) with OrderedDict
            if len(self._cache) >= self._max:
                self._cache.popitem(last=False)
                metrics.increment("dns_cache.eviction")
            self._cache[ip] = (hostname, time.time() + ttl)

    def clear(self) -> None:
        """Flush all cached entries and pending lookups."""
        with self._lock:
            self._cache.clear()
        self._pending.clear()
