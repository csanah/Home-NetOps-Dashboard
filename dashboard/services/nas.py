import os
import threading
import paramiko

# ── SSH Connection Pool ──
_ssh_client = None
_ssh_lock = threading.Lock()


def _create_ssh_client():
    host = os.environ.get("NAS_HOST", "")
    password = os.environ.get("NAS_SSH_PASS", "")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def kb_handler(title, instructions, prompt_list):
        return [password] * len(prompt_list)

    username = os.environ.get("NAS_SSH_USER", "")
    client.connect(
        hostname=host,
        port=22,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
        timeout=5,
    )
    transport = client.get_transport()
    if transport and not transport.is_authenticated():
        transport.auth_interactive(username, kb_handler)
    return client


def _get_or_create_ssh():
    """Get or create a persistent SSH client for the NAS."""
    global _ssh_client
    with _ssh_lock:
        if _ssh_client is not None:
            try:
                transport = _ssh_client.get_transport()
                if transport and transport.is_active():
                    transport.send_ignore()
                    return _ssh_client
            except Exception:
                try:
                    _ssh_client.close()
                except Exception:
                    pass
                _ssh_client = None
        _ssh_client = _create_ssh_client()
        return _ssh_client


def _format_uptime(seconds):
    seconds = int(float(seconds))
    d = seconds // 86400
    h = (seconds % 86400) // 3600
    m = (seconds % 3600) // 60
    if d > 0:
        return f"{d}d {h}h {m}m"
    if h > 0:
        return f"{h}h {m}m"
    return f"{m}m"


def get_health():
    host = os.environ.get("NAS_HOST", "")
    info = {
        "name": "Synology NAS",
        "host": host,
        "online": False,
        "total": None,
        "used": None,
        "pct": None,
        "uptime": None,
        "temp_c": None,
    }
    try:
        client = _get_or_create_ssh()
        info["online"] = True

        # Disk usage
        stdin, stdout, stderr = client.exec_command("df -h /volume1", timeout=5)
        lines = stdout.read().decode("utf-8", errors="replace").strip().split("\n")
        if len(lines) >= 2:
            parts = lines[1].split()
            if len(parts) >= 5:
                info["total"] = parts[1]
                info["used"] = parts[2]
                info["pct"] = parts[4].rstrip("%")

        # Uptime
        stdin, stdout, stderr = client.exec_command("cat /proc/uptime", timeout=5)
        uptime_raw = stdout.read().decode("utf-8", errors="replace").strip()
        if uptime_raw:
            info["uptime"] = _format_uptime(uptime_raw.split()[0])

        # Temperature
        stdin, stdout, stderr = client.exec_command(
            "cat /sys/bus/platform/devices/therm_sys/temp1_input 2>/dev/null", timeout=5
        )
        temp_raw = stdout.read().decode("utf-8", errors="replace").strip()
        if temp_raw and temp_raw.isdigit():
            info["temp_c"] = int(temp_raw) // 1000

    except Exception:
        # Connection failed — clear pooled client so next call retries
        global _ssh_client
        with _ssh_lock:
            try:
                if _ssh_client:
                    _ssh_client.close()
            except Exception:
                pass
            _ssh_client = None

    return info
