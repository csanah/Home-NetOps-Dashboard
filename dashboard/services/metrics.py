"""Lightweight metrics collection: counters, histograms, gauges."""
from __future__ import annotations

import threading
import time
from collections import deque
from contextlib import contextmanager


class Metrics:
    """Thread-safe metrics singleton with counters, histograms, and gauges."""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._counters = {}
                    cls._instance._histograms = {}
                    cls._instance._gauges = {}
                    cls._instance._data_lock = threading.Lock()
        return cls._instance

    def increment(self, name: str, amount: int = 1) -> None:
        """Increment a counter."""
        with self._data_lock:
            self._counters[name] = self._counters.get(name, 0) + amount

    def observe(self, name: str, value: float) -> None:
        """Record an observation in a histogram (deque maxlen=100)."""
        with self._data_lock:
            if name not in self._histograms:
                self._histograms[name] = deque(maxlen=100)
            self._histograms[name].append(value)

    def set_gauge(self, name: str, value: float) -> None:
        """Set a gauge to a specific value."""
        with self._data_lock:
            self._gauges[name] = value

    @contextmanager
    def timed(self, name: str):
        """Context manager that records duration in ms to a histogram."""
        start = time.time()
        try:
            yield
        finally:
            duration_ms = (time.time() - start) * 1000
            self.observe(name, duration_ms)

    def snapshot(self) -> dict:
        """Return all current metrics as a dict."""
        with self._data_lock:
            result = {
                "counters": dict(self._counters),
                "gauges": dict(self._gauges),
                "histograms": {},
            }
            for name, values in self._histograms.items():
                vals = list(values)
                if vals:
                    result["histograms"][name] = {
                        "count": len(vals),
                        "avg": round(sum(vals) / len(vals), 2),
                        "min": round(min(vals), 2),
                        "max": round(max(vals), 2),
                        "last": round(vals[-1], 2),
                    }
            return result

    def get_counter(self, name: str) -> int:
        with self._data_lock:
            return self._counters.get(name, 0)

    def get_gauge(self, name: str) -> float:
        with self._data_lock:
            return self._gauges.get(name, 0.0)

    def reset(self) -> None:
        """Reset all metrics (for testing)."""
        with self._data_lock:
            self._counters.clear()
            self._histograms.clear()
            self._gauges.clear()


# Module-level singleton
metrics = Metrics()
