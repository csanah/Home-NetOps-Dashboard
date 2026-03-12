from __future__ import annotations

import logging
import os
import re
import shlex
import threading
from concurrent.futures import ThreadPoolExecutor

from .ssh_utils import safe_close
from .ssh_pool import SSHPool

logger = logging.getLogger(__name__)


def _get_ssh_client():
    """Create an SSH client to the UDM Pro using keyboard-interactive auth."""
    from .ssh_utils import create_ssh_client
    from .config import TIMEOUTS
    return create_ssh_client(
        host=os.environ.get("UDM_HOST", ""),
        username=os.environ.get("UDM_SSH_USER", "root"),
        password=os.environ.get("UDM_SSH_PASS", ""),
        use_kb_interactive=True,
        timeout=TIMEOUTS["ssh_connect"],
    )


_lookup_pool = SSHPool("firewall_lookup", _get_ssh_client)


def _validate_lookup_input(s: str) -> bool:
    """Validate IP, CIDR, or domain name for firewall lookup."""
    import ipaddress as _ipaddr
    try:
        _ipaddr.ip_address(s)
        return True
    except ValueError:
        pass
    try:
        _ipaddr.ip_network(s, strict=False)
        return True
    except ValueError:
        pass
    return bool(re.match(r'^[a-zA-Z0-9][a-zA-Z0-9.\-]*$', s))


def lookup(ip_or_domain: str) -> dict[str, str]:
    """Run lookup commands on UDM Pro for a given IP or domain (parallelized)."""
    # Validate input to prevent command injection (root shell on UDM Pro)
    if not _validate_lookup_input(ip_or_domain):
        return {"error": "Invalid IP or domain format"}

    results = {}
    try:
        client = _lookup_pool.get()
        safe_target = shlex.quote(ip_or_domain)

        commands = {
            "nslookup": f"nslookup {safe_target} 2>&1 | head -20",
            "ipset_alien": f"ipset test ALIEN {safe_target} 2>&1",
            "ipset_tor": f"ipset test TOR {safe_target} 2>&1",
            "ipset_ips": f"ipset test ips {safe_target} 2>&1",
            "geoip": "iptables -L UBIOS_IN_GEOIP -n -v 2>&1 | head -30",
            "conntrack": f"conntrack -L 2>&1 | grep {safe_target} | head -20",
        }

        def run_cmd(key_cmd):
            """Execute a single SSH command and return its key + output."""
            key, cmd = key_cmd
            try:
                stdin, stdout, stderr = client.exec_command(cmd, timeout=10)
                output = stdout.read().decode("utf-8", errors="replace")
                err = stderr.read().decode("utf-8", errors="replace")
                return key, output + err
            except Exception as e:
                return key, f"Error: {e}"

        with ThreadPoolExecutor(max_workers=6) as pool:
            for key, output in pool.map(run_cmd, commands.items()):
                results[key] = output

    except Exception as e:
        # Connection failed — clear pooled client so next call retries
        _lookup_pool.invalidate()
        results["error"] = f"SSH connection failed: {e}"

    return results


def start_log_stream(socketio, namespace: str, mode: str = "all", filter_ip: str | None = None, scope: str = "both") -> tuple[threading.Event, callable]:
    """Start streaming firewall logs via SSH. Returns a stop event.

    mode="all": tcpdump on br0 (all live traffic)
    mode="blocked": tail firewall log files (blocked/dropped only)
    filter_ip: optional IP to filter server-side
    scope: "both", "local" (internal only), "external" (WAN traffic)
    """
    if mode not in ("all", "blocked"):
        mode = "all"
    if scope not in ("both", "local", "external"):
        scope = "both"
    if filter_ip and not re.match(r"^\d{1,3}(\.\d{1,3}){3}$", filter_ip):
        filter_ip = None

    stop_event = threading.Event()

    def stream_worker():
        """Run SSH command and emit log lines over WebSocket until stopped."""
        try:
            # Stream always gets its own dedicated connection
            client = _get_ssh_client()
            socketio.emit("stream_status", {"status": "connected", "mode": mode}, namespace=namespace)

            channel = client.get_transport().open_session()

            if mode == "blocked":
                cmd = "tail -F /var/log/ulog/syslogemu.log /var/log/ulog/threat.log 2>/dev/null"
                grep_parts = []
                if filter_ip:
                    grep_parts.append(filter_ip)
                if scope == "local":
                    grep_parts.append("192.168.")
                elif scope == "external":
                    # blocked logs with non-local IPs — invert grep for 192.168
                    pass  # handled below
                if grep_parts:
                    cmd += f" | grep --line-buffered '{grep_parts[0]}'"
                    for p in grep_parts[1:]:
                        cmd += f" | grep --line-buffered '{p}'"
                if scope == "external" and not filter_ip:
                    cmd += " | grep --line-buffered -v 'SRC=192.168.'"
            else:
                # Build tcpdump filter expression
                filters = []
                if filter_ip:
                    filters.append(f"host {filter_ip}")
                if scope == "local":
                    filters.append("src net 192.168.0.0/16 and dst net 192.168.0.0/16")
                elif scope == "external":
                    filters.append("not (src net 192.168.0.0/16 and dst net 192.168.0.0/16)")

                cmd = "tcpdump -l -n -q -i br0"
                if filters:
                    expr = " and ".join(f"({f})" for f in filters)
                    cmd += f" '{expr}'"

            channel.settimeout(1.0)
            channel.exec_command(cmd)

            buf = ""
            while not stop_event.is_set():
                if channel.recv_ready():
                    data = channel.recv(4096).decode("utf-8", errors="replace")
                    buf += data
                    # Cap buffer at 64KB: tcpdump can burst faster than we emit,
                    # so truncate to the newest 32KB to avoid runaway memory use.
                    if len(buf) > 65536:
                        buf = buf[-32768:]
                    # Emit lines in batches of 10, yielding between batches.
                    # Without this, a high-traffic burst could starve the stop_event
                    # check and make the stream unresponsive to user stop requests.
                    lines_sent = 0
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            socketio.emit("log_line", {"line": line}, namespace=namespace)
                            lines_sent += 1
                        if lines_sent >= 10:
                            break
                    if lines_sent >= 10:
                        stop_event.wait(0.01)  # brief yield to let stop signals through
                elif channel.exit_status_ready():
                    break
                else:
                    stop_event.wait(0.1)

            # Force-close transport to kill remote tcpdump/tail immediately
            try:
                transport = client.get_transport()
                if transport:
                    transport.close()
            except Exception as e:
                logger.debug("Failed to close stream transport: %s", e)
            safe_close(client)
        except Exception as e:
            socketio.emit("stream_status", {"status": "error", "message": str(e)}, namespace=namespace)

        socketio.emit("stream_status", {"status": "disconnected"}, namespace=namespace)

    return stop_event, stream_worker
