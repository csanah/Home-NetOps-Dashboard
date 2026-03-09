import socket
import time
import ipaddress
from concurrent.futures import ThreadPoolExecutor


class DNSCache:
    """Async reverse DNS resolver with in-memory cache."""

    def __init__(self, max_entries=2000, success_ttl=600, failure_ttl=300):
        self._cache = {}          # ip -> (hostname|None, expire_time)
        self._pending = set()     # IPs currently being resolved
        self._max = max_entries
        self._success_ttl = success_ttl
        self._failure_ttl = failure_ttl
        self._pool = ThreadPoolExecutor(max_workers=4)

    @staticmethod
    def is_external(ip):
        """Return True if IP is not in a private/reserved range."""
        try:
            addr = ipaddress.ip_address(ip)
            return not (addr.is_private or addr.is_loopback
                        or addr.is_link_local or addr.is_multicast)
        except ValueError:
            return False

    def lookup(self, ip, callback):
        """Look up hostname for ip. Calls callback(ip, hostname) when done.
        Returns cached result immediately if available, otherwise schedules async lookup.
        """
        now = time.time()

        # Check cache
        if ip in self._cache:
            hostname, expires = self._cache[ip]
            if now < expires:
                if hostname:
                    callback(ip, hostname)
                return  # cached (hit or negative)

        # Skip if already pending
        if ip in self._pending:
            return

        self._pending.add(ip)
        self._pool.submit(self._resolve, ip, callback)

    def _resolve(self, ip, callback):
        try:
            hostname, _, _ = socket.gethostbyaddr(ip)
            self._store(ip, hostname)
            callback(ip, hostname)
        except (socket.herror, socket.gaierror, OSError):
            self._store(ip, None)
        finally:
            self._pending.discard(ip)

    def _store(self, ip, hostname):
        # Evict oldest if at capacity
        if len(self._cache) >= self._max:
            oldest = min(self._cache, key=lambda k: self._cache[k][1])
            del self._cache[oldest]

        ttl = self._success_ttl if hostname else self._failure_ttl
        self._cache[ip] = (hostname, time.time() + ttl)

    def clear(self):
        self._cache.clear()
        self._pending.clear()
