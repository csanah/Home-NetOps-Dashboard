import os
import time
from collections import deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from . import udm, proxmox, homeassistant, portcheck, nas

# ── Circuit Breaker ──
# Per-system state: {failures, skip_until, last_good}
_circuit_state = {}


def _check_with_circuit(key, fn):
    state = _circuit_state.setdefault(key, {"failures": 0, "skip_until": 0, "last_good": None})
    now = time.time()

    # If circuit is open (too many failures), return cached or offline stub
    if state["failures"] >= 3 and now < state["skip_until"]:
        if state["last_good"] is not None:
            result = dict(state["last_good"])
            result["circuit_open"] = True
            return result
        return {"name": key, "online": False, "circuit_open": True}

    try:
        result = fn()
        if result.get("online", False):
            state["failures"] = 0
            state["last_good"] = result
        else:
            state["failures"] += 1
            state["skip_until"] = now + 60
        return result
    except Exception:
        state["failures"] += 1
        state["skip_until"] = now + 60
        if state["last_good"] is not None:
            result = dict(state["last_good"])
            result["circuit_open"] = True
            return result
        return {"name": key, "online": False}


# ── Uptime History ──
# key -> deque of booleans (True=online), last 30 checks (~15 min at 30s interval)
_health_history = {}


def _record_history(results):
    for key in ("udm", "proxmox", "ha", "nas", "mqtt", "media_center"):
        if key not in _health_history:
            _health_history[key] = deque(maxlen=30)
        online = results.get(key, {}).get("online", False)
        _health_history[key].append(online)


def get_health_history():
    return {k: list(v) for k, v in _health_history.items()}


def _is_card_visible(key):
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
    return os.environ.get(env_key, "true").lower() != "false"


def get_all_health():
    results = {}
    all_checks = {
        "udm": udm.get_health,
        "proxmox": proxmox.get_health,
        "ha": homeassistant.get_health,
        "nas": nas.get_health,
        "mqtt": portcheck.get_mqtt_health,
        "media_center": proxmox.get_media_center_stats,
    }
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
            except Exception:
                results[key] = [] if key == "bandwidth" else {"name": key, "online": False}

    _record_history(results)
    return results


def get_alerts(health):
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
