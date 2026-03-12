import logging
import os
from .utils import format_uptime as _shared_format_uptime
from .ssh_utils import create_ssh_client
from .ssh_pool import SSHPool
from .config import TIMEOUTS

logger = logging.getLogger(__name__)


def _create_ssh_client():
    return create_ssh_client(
        host=os.environ.get("NAS_HOST", ""),
        username=os.environ.get("NAS_SSH_USER", ""),
        password=os.environ.get("NAS_SSH_PASS", ""),
        use_kb_interactive=True,
        timeout=TIMEOUTS["ssh_connect"],
    )


_ssh_pool = SSHPool("nas", _create_ssh_client)


def _format_uptime(seconds):
    return _shared_format_uptime(seconds)


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
        client = _ssh_pool.get()
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

    except Exception as e:
        logger.debug("NAS health check failed: %s", e)
        # Connection failed — clear pooled client so next call retries
        _ssh_pool.invalidate()

    return info
