import logging
import os
import time
import threading
from .http_client import get_shared_session
from .utils import format_uptime as _shared_format_uptime

logger = logging.getLogger(__name__)

_session = get_shared_session()


def format_rate(bps):
    """Format bytes/sec as human-readable rate."""
    if bps >= 1_000_000:
        return f"{bps / 1_000_000:.1f} Mbps"
    if bps >= 1_000:
        return f"{bps / 1_000:.0f} Kbps"
    return f"{bps:.0f} bps"


def format_uptime(seconds):
    return _shared_format_uptime(seconds)


def get_health():
    host = os.environ.get("UDM_HOST", "")
    api_key = os.environ.get("UDM_API_KEY", "")
    info = {
        "name": "UDM Pro",
        "host": host,
        "online": False,
        "clients": "?",
        "wan_ip": "?",
        "uptime": "?",
        "cpu": "?",
        "mem": "?",
        "isp": "",
    }
    try:
        r = _session.get(
            f"https://{host}/proxy/network/api/s/default/stat/health",
            headers={"X-API-KEY": api_key},
            verify=False,
            timeout=(3, 8),
        )
        r.raise_for_status()
        data = r.json().get("data", r.json())
    except Exception:
        return info

    info["online"] = True
    if isinstance(data, list):
        for sub in data:
            if sub.get("subsystem") == "wan":
                info["wan_ip"] = sub.get("wan_ip", "?")
                info["clients"] = sub.get("num_sta", "?")
                gw = sub.get("gw_system-stats", {})
                if gw.get("uptime"):
                    info["uptime"] = format_uptime(gw["uptime"])
                if gw.get("cpu"):
                    info["cpu"] = gw["cpu"] + "%"
                if gw.get("mem"):
                    info["mem"] = gw["mem"] + "%"
                info["isp"] = sub.get("isp_name", "")
                info["wan_down_bps"] = sub.get("rx_bytes-r", 0)
                info["wan_up_bps"] = sub.get("tx_bytes-r", 0)
    return info


# Manufacturer keywords for categorization
_PHONE_HINTS = {"apple", "samsung", "google", "pixel", "oneplus", "xiaomi", "huawei", "iphone", "ipad", "android"}
_COMPUTER_HINTS = {"windows", "mac", "dell", "lenovo", "hp", "asus", "acer", "thinkpad", "surface", "intel", "desktop", "laptop", "pc"}


def _categorize(client):
    """Categorize a client as phone, computer, or other."""
    dev_type = (client.get("type") or "").lower()
    name = (client.get("name") or client.get("hostname") or "").lower()
    oui = (client.get("oui") or "").lower()
    combined = f"{dev_type} {name} {oui}"

    if any(h in combined for h in _PHONE_HINTS):
        return "phone"
    if any(h in combined for h in _COMPUTER_HINTS):
        return "computer"
    return "other"


# ── Stat/STA cache (15s TTL) ──
_sta_cache = {"data": None, "expires": 0}
_sta_lock = threading.Lock()


def _get_sta_data():
    """Return cached /stat/sta response if fresh, otherwise fetch and cache."""
    now = time.time()
    with _sta_lock:
        if _sta_cache["data"] is not None and now < _sta_cache["expires"]:
            return _sta_cache["data"]

    host = os.environ.get("UDM_HOST", "")
    api_key = os.environ.get("UDM_API_KEY", "")
    r = _session.get(
        f"https://{host}/proxy/network/api/s/default/stat/sta",
        headers={"X-API-KEY": api_key},
        verify=False,
        timeout=8,
    )
    r.raise_for_status()
    data = r.json().get("data", [])

    with _sta_lock:
        _sta_cache["data"] = data
        _sta_cache["expires"] = time.time() + 15
    return data


def get_clients():
    """Fetch connected clients from UDM Pro API."""
    try:
        raw = _get_sta_data()
    except Exception:
        return []

    clients = []
    for c in raw:
        ip = c.get("ip")
        if not ip:
            continue
        name = c.get("name") or c.get("hostname") or c.get("mac", "Unknown")
        category = _categorize(c)
        clients.append({
            "name": name,
            "ip": ip,
            "mac": c.get("mac", ""),
            "category": category,
        })

    clients.sort(key=lambda x: x["name"].lower())
    return clients


def get_all_clients():
    """Fetch all known clients (online + offline) from UDM Pro API."""
    # Get active clients (online now) — uses cached sta data
    online_macs = set()
    active_ips = {}
    active_wired = {}  # mac -> bool (is_wired from active clients)
    try:
        for c in _get_sta_data():
            mac = c.get("mac", "").lower()
            if mac:
                online_macs.add(mac)
                if c.get("ip"):
                    active_ips[mac] = c["ip"]
                if "is_wired" in c:
                    active_wired[mac] = bool(c["is_wired"])
    except Exception as e:
        logger.debug("Failed to fetch STA data for all_clients: %s", e)

    # Get all known clients (ever connected)
    host = os.environ.get("UDM_HOST", "")
    api_key = os.environ.get("UDM_API_KEY", "")
    all_raw = []
    try:
        r = _session.get(
            f"https://{host}/proxy/network/api/s/default/rest/user",
            headers={"X-API-KEY": api_key}, verify=False, timeout=10,
        )
        r.raise_for_status()
        all_raw = r.json().get("data", [])
    except Exception as e:
        logger.debug("Failed to fetch /rest/user: %s", e)

    clients = []
    seen_macs = set()
    for c in all_raw:
        mac = (c.get("mac") or "").lower()
        if not mac or mac in seen_macs:
            continue
        seen_macs.add(mac)
        is_online = mac in online_macs
        ip = active_ips.get(mac) or c.get("last_ip") or c.get("ip") or ""
        name = c.get("name") or c.get("hostname") or mac
        category = _categorize(c)
        # Determine wired/wireless: prefer active data, fall back to rest/user
        if mac in active_wired:
            wired = active_wired[mac]
        elif "is_wired" in c:
            wired = bool(c["is_wired"])
        else:
            wired = None  # unknown
        clients.append({
            "name": name,
            "ip": ip,
            "mac": mac,
            "category": category,
            "online": is_online,
            "wired": wired,
        })

    clients.sort(key=lambda x: (not x["online"], x["name"].lower()))
    return clients


def get_top_clients(limit=5):
    """Fetch top clients by total bandwidth from UDM Pro API."""
    try:
        raw = _get_sta_data()
    except Exception:
        return []

    clients = []
    for c in raw:
        ip = c.get("ip")
        if not ip:
            continue
        name = c.get("name") or c.get("hostname") or c.get("mac", "Unknown")
        tx = c.get("tx_bytes", 0)
        rx = c.get("rx_bytes", 0)
        clients.append({
            "name": name,
            "ip": ip,
            "down": rx,
            "up": tx,
            "total": tx + rx,
        })

    clients.sort(key=lambda x: x["total"], reverse=True)
    for c in clients[:limit]:
        c["down_fmt"] = format_rate(c["down"])
        c["up_fmt"] = format_rate(c["up"])
    return clients[:limit]


def get_firewall_rules():
    """Fetch firewall policies and traffic rules from UDM Pro."""
    host = os.environ.get("UDM_HOST", "")
    api_key = os.environ.get("UDM_API_KEY", "")
    headers = {"X-API-KEY": api_key}
    rules = []

    # Zone-based firewall policies
    try:
        r = _session.get(
            f"https://{host}/proxy/network/v2/api/site/default/firewall-policies",
            headers=headers,
            verify=False,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        # Response may be a list or wrapped in a key
        items = data if isinstance(data, list) else data.get("data", data.get("firewall_policies", []))
        if isinstance(items, list):
            for p in items:
                rules.append({
                    "name": p.get("name", p.get("description", "Unnamed Policy")),
                    "action": p.get("action", "unknown"),
                    "source_zone": p.get("source", {}).get("zone", p.get("src_zone", "-")),
                    "dest_zone": p.get("destination", {}).get("zone", p.get("dst_zone", "-")),
                    "protocol": p.get("protocol", "Any"),
                    "enabled": p.get("enabled", True),
                    "type": "policy",
                })
    except Exception as e:
        logger.debug("Failed to fetch firewall policies: %s", e)

    # Traffic rules
    try:
        r = _session.get(
            f"https://{host}/proxy/network/v2/api/site/default/trafficrules",
            headers=headers,
            verify=False,
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
        items = data if isinstance(data, list) else data.get("data", data.get("traffic_rules", []))
        if isinstance(items, list):
            for t in items:
                rules.append({
                    "name": t.get("description", t.get("name", "Unnamed Rule")),
                    "action": t.get("action", t.get("target_action", "unknown")),
                    "source_zone": t.get("matching_target", "-"),
                    "dest_zone": t.get("target", "-"),
                    "protocol": t.get("protocol", "Any"),
                    "enabled": t.get("enabled", True),
                    "type": "traffic",
                })
    except Exception as e:
        logger.debug("Failed to fetch traffic rules: %s", e)

    return rules
