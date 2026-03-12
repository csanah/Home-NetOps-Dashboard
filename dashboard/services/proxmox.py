import logging
import os
from .http_client import get_shared_session
from .utils import format_uptime as _shared_format_uptime

logger = logging.getLogger(__name__)

_session = get_shared_session()


def format_bytes(b):
    if b >= 1e12:
        return f"{b / 1e12:.1f} TB"
    if b >= 1e9:
        return f"{b / 1e9:.1f} GB"
    return f"{b / 1e6:.0f} MB"


def format_uptime(seconds):
    return _shared_format_uptime(seconds)


def get_health():
    host = os.environ.get("PROXMOX_HOST", "")
    port = os.environ.get("PROXMOX_PORT", "8006")
    token = os.environ.get("PROXMOX_TOKEN", "")
    headers = {"Authorization": f"PVEAPIToken={token}"}
    base = f"https://{host}:{port}/api2/json"

    info = {
        "name": "Proxmox",
        "host": f"{host}:{port}",
        "online": False,
        "cpu": "?",
        "ram": "?",
        "ram_detail": "",
        "vms": [],
    }

    # Node status
    try:
        node = os.environ.get("PROXMOX_NODE", "")
        r = _session.get(f"{base}/nodes/{node}/status", headers=headers, verify=False, timeout=(3, 8))
        r.raise_for_status()
        d = r.json().get("data", {})
        info["online"] = True
        if d.get("cpu") is not None:
            info["cpu"] = f"{d['cpu'] * 100:.0f}%"
        if d.get("memory"):
            used = d["memory"].get("used", 0)
            total = d["memory"].get("total", 1)
            pct = used / total * 100
            info["ram"] = f"{pct:.0f}%"
            info["ram_detail"] = f"{format_bytes(used)}/{format_bytes(total)}"
    except Exception as e:
        logger.debug("Failed to fetch Proxmox node status: %s", e)

    # VMs
    try:
        r = _session.get(f"{base}/nodes/{node}/qemu", headers=headers, verify=False, timeout=(3, 8))
        r.raise_for_status()
        for vm in r.json().get("data", []):
            info["online"] = True
            info["vms"].append({
                "id": vm.get("vmid"),
                "name": vm.get("name", f"VM {vm.get('vmid')}"),
                "status": vm.get("status", "unknown"),
                "type": "vm",
                "cpu_pct": round(vm.get("cpu", 0) * 100, 1) if vm.get("status") == "running" else None,
                "mem_used": vm.get("mem", 0),
                "mem_max": vm.get("maxmem", 0),
            })
    except Exception as e:
        logger.debug("Failed to fetch Proxmox VMs: %s", e)

    # LXC containers
    try:
        r = _session.get(f"{base}/nodes/{node}/lxc", headers=headers, verify=False, timeout=(3, 8))
        r.raise_for_status()
        for ct in r.json().get("data", []):
            info["online"] = True
            info["vms"].append({
                "id": ct.get("vmid"),
                "name": ct.get("name", f"CT {ct.get('vmid')}"),
                "status": ct.get("status", "unknown"),
                "type": "ct",
                "cpu_pct": round(ct.get("cpu", 0) * 100, 1) if ct.get("status") == "running" else None,
                "mem_used": ct.get("mem", 0),
                "mem_max": ct.get("maxmem", 0),
            })
    except Exception as e:
        logger.debug("Failed to fetch Proxmox LXC containers: %s", e)

    info["vms"].sort(key=lambda v: v["id"])
    return info


def get_media_center_stats():
    """Fetch detailed stats for VM 901 (Media Center)."""
    host = os.environ.get("PROXMOX_HOST", "")
    port = os.environ.get("PROXMOX_PORT", "8006")
    token = os.environ.get("PROXMOX_TOKEN", "")
    node = os.environ.get("PROXMOX_NODE", "")
    headers = {"Authorization": f"PVEAPIToken={token}"}
    base = f"https://{host}:{port}/api2/json"

    info = {
        "name": "Media Center",
        "host": "VM 901",
        "online": False,
        "cpu": "?",
        "mem": "?",
        "mem_detail": "",
        "netin": "?",
        "netout": "?",
        "uptime": "?",
        "diskread": "?",
        "diskwrite": "?",
    }
    try:
        r = _session.get(
            f"{base}/nodes/{node}/qemu/901/status/current",
            headers=headers, verify=False, timeout=(3, 8),
        )
        r.raise_for_status()
        d = r.json().get("data", {})
        if d.get("status") == "running":
            info["online"] = True
            info["status"] = "running"
        else:
            info["status"] = d.get("status", "stopped")
            return info

        # CPU
        if d.get("cpu") is not None:
            info["cpu"] = f"{d['cpu'] * 100:.1f}%"

        # Memory
        mem_used = d.get("mem", 0)
        mem_max = d.get("maxmem", 1)
        info["mem"] = f"{mem_used / mem_max * 100:.0f}%"
        info["mem_detail"] = f"{format_bytes(mem_used)}/{format_bytes(mem_max)}"

        # Network (cumulative bytes since boot)
        info["netin"] = format_bytes(d.get("netin", 0))
        info["netout"] = format_bytes(d.get("netout", 0))

        # Uptime
        info["uptime"] = format_uptime(d.get("uptime", 0))

        # Disk I/O
        info["diskread"] = format_bytes(d.get("diskread", 0))
        info["diskwrite"] = format_bytes(d.get("diskwrite", 0))

    except Exception as e:
        logger.debug("Failed to fetch media center stats: %s", e)
    return info
