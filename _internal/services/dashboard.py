from __future__ import annotations

import logging
import os
import time
import threading
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Callable
from . import udm, proxmox, homeassistant, portcheck, nas
from .metrics import metrics

logger = logging.getLogger(__name__)

# ── Health Check Cache (20s TTL) ──
_cached_result = None
_cache_time = 0
_cache_lock = threading.Lock()
_CACHE_TTL = 20

# ── Circuit Breaker ──
# Per-system state: {failures, skip_until, last_good}
_circuit_state = {}
_circuit_lock = threading.Lock()


def _check_with_circuit(key: str, fn: Callable[[], dict]) -> dict:
    """Run a health check with circuit breaker protection to avoid hammering downed services."""
    with _circuit_lock:
        state = _circuit_state.setdefault(key, {"failures": 0, "skip_until": 0, "last_good": None})
        now = time.time()

        # OPEN state: 3+ consecutive failures within cooldown window — skip the
        # actual check entirely to avoid slow timeouts piling up on a dead service.
        if state["failures"] >= 3 and now < state["skip_until"]:
            remaining = int(state["skip_until"] - now)
            logger.warning("Circuit breaker OPEN for %s — retrying in %ds", key, remaining)
            # Serve stale cached result so the UI still shows last-known stats
            if state["last_good"] is not None:
                result = dict(state["last_good"])
                result["circuit_open"] = True
                result["circuit_cooldown_remaining"] = remaining
                result["circuit_last_failure"] = state["skip_until"] - 60
                return result
            return {"name": key, "online": False, "circuit_open": True,
                    "circuit_cooldown_remaining": remaining}

    # HALF-OPEN / CLOSED: cooldown expired or failures < 3 — attempt the real check.
    try:
        result = fn()
        with _circuit_lock:
            if result.get("online", False):
                # Success → CLOSED: reset failure counter so future checks proceed normally
                if state["failures"] > 0:
                    logger.info("Circuit breaker CLOSED for %s — service recovered", key)
                state["failures"] = 0
                state["last_good"] = result
            else:
                # Soft failure (returned offline) — increment toward the open threshold
                state["failures"] += 1
                state["skip_until"] = time.time() + 60
        return result
    except Exception as exc:
        # Hard failure (exception) — same escalation toward open state
        with _circuit_lock:
            state["failures"] += 1
            state["skip_until"] = time.time() + 60
        logger.warning("Circuit breaker: %s failed (%d failures) — %s", key, state["failures"], exc)
        # Degrade gracefully: return stale data rather than an empty card
        with _circuit_lock:
            if state["last_good"] is not None:
                result = dict(state["last_good"])
                result["circuit_open"] = True
                return result
        return {"name": key, "online": False}


# ── Uptime History ──
# key -> deque of booleans (True=online), last 30 checks (~15 min at 30s interval)
_health_history = {}


def _record_history(results: dict) -> None:
    """Append each system's online/offline state to its sparkline history deque."""
    for key in ("udm", "proxmox", "ha", "nas", "mqtt", "media_center"):
        if key not in _health_history:
            _health_history[key] = deque(maxlen=30)
        online = results.get(key, {}).get("online", False)
        _health_history[key].append(online)


def get_health_history() -> dict[str, list[bool]]:
    """Return a snapshot of each system's recent up/down history for sparkline rendering."""
    return {k: list(v) for k, v in _health_history.items()}


def _is_card_visible(key: str) -> bool:
    """Check if a dashboard card is enabled via SHOW_* env vars."""
    env_map = {
        "udm": "SHOW_UDM",
        "proxmox": "SHOW_PROXMOX",
        "ha": "SHOW_HA",
        "nas": "SHOW_NAS",
        "mqtt": "SHOW_MQTT",
        "media_center": "SHOW_MEDIA_CENTER",
    }
    env_key = env_map.get(key)
    if not env_key:
        return True
    return os.environ.get(env_key, "false").lower() == "true"


def get_all_health() -> dict:
    """Aggregate health from all systems, returning cached results within the TTL window."""
    global _cached_result, _cache_time

    # Fast path (no lock): if cache is fresh, return immediately.
    # This avoids lock contention when many HTMX requests arrive simultaneously.
    now = time.time()
    if _cached_result is not None and (now - _cache_time) < _CACHE_TTL:
        return dict(_cached_result)

    with _cache_lock:
        # Double-check inside lock: another thread may have refreshed the cache
        # while we waited for the lock, preventing redundant parallel fetches
        # (thundering herd problem).
        now = time.time()
        if _cached_result is not None and (now - _cache_time) < _CACHE_TTL:
            metrics.increment("health_cache.hit")
            return dict(_cached_result)

        metrics.increment("health_cache.miss")
        with metrics.timed("health_check.duration_ms"):
            results = _fetch_all_health()
        _cached_result = results
        _cache_time = time.time()
        return dict(results)


def _fetch_all_health():
    """Run all enabled health checks in parallel via thread pool and collect results."""
    results = {}
    all_checks = {
        "udm": udm.get_health,
        "proxmox": proxmox.get_health,
        "ha": homeassistant.get_health,
        "nas": nas.get_health,
        "mqtt": portcheck.get_mqtt_health,
        "media_center": proxmox.get_media_center_stats,
    }
    # Only run checks for cards the user hasn't disabled via SHOW_* env vars
    checks = {k: fn for k, fn in all_checks.items() if _is_card_visible(k)}
    with ThreadPoolExecutor(max_workers=7) as pool:
        futures = {
            pool.submit(_check_with_circuit, key, fn): key
            for key, fn in checks.items()
        }
        # bandwidth doesn't go through circuit breaker (returns list, not dict)
        futures[pool.submit(udm.get_top_clients)] = "bandwidth"
        for future in as_completed(futures):
            key = futures[future]
            try:
                results[key] = future.result()
            except Exception as e:
                logger.warning("Health check %s failed: %s", key, e)
                results[key] = [] if key == "bandwidth" else {"name": key, "online": False}

    _record_history(results)
    return results


def get_alerts(health: dict) -> list[dict[str, str]]:
    """Generate user-facing alert messages for any offline systems or stopped VMs."""
    alerts = []
    labels = {
        "udm": (os.environ.get("NAME_UDM", "UDM Pro"), "no network management"),
        "proxmox": (os.environ.get("NAME_PROXMOX", "Proxmox"), "VMs may be down"),
        "ha": (os.environ.get("NAME_HA", "Home Assistant"), "automations offline"),
        "nas": (os.environ.get("NAME_NAS", "Synology NAS"), "check power/network"),
        "mqtt": (os.environ.get("NAME_MQTT", "MQTT Broker"), "HASS.Agent and IoT devices disconnected"),
        "media_center": (os.environ.get("NAME_MEDIA_CENTER", "Media Center"), "VM 901 unreachable"),
    }
    for key, (name, detail) in labels.items():
        sys = health.get(key, {})
        if not sys.get("online", False):
            msg = f"{name} is unreachable"
            if detail:
                msg += f" — {detail}"
            if sys.get("circuit_open"):
                msg += " (circuit open — retrying in 60s)"
            alerts.append({"level": "error", "message": msg})

    # Stopped Proxmox VMs
    px = health.get("proxmox", {})
    if px.get("online"):
        stopped = [v for v in px.get("vms", []) if v["status"] == "stopped"]
        if stopped:
            names = ", ".join(v["name"] for v in stopped)
            alerts.append({"level": "warning", "message": f"Proxmox: {len(stopped)} VM(s) stopped: {names}"})

    return alerts
