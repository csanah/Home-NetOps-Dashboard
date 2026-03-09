import os
import re
import threading
from concurrent.futures import ThreadPoolExecutor
import paramiko


def _get_ssh_client():
    host = os.environ.get("UDM_HOST", "")
    password = os.environ.get("UDM_SSH_PASS", "")
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    # UDM Pro uses keyboard-interactive auth
    def kb_handler(title, instructions, prompt_list):
        return [password] * len(prompt_list)

    username = os.environ.get("UDM_SSH_USER", "root")
    client.connect(
        hostname=host,
        port=22,
        username=username,
        password=password,
        look_for_keys=False,
        allow_agent=False,
    )
    transport = client.get_transport()
    if transport and not transport.is_authenticated():
        transport.auth_interactive(username, kb_handler)
    return client


# ── SSH Connection Pool for lookup ──
_lookup_ssh = None
_lookup_ssh_lock = threading.Lock()


def _get_or_create_lookup_ssh():
    """Get or create a persistent SSH client for lookups."""
    global _lookup_ssh
    with _lookup_ssh_lock:
        if _lookup_ssh is not None:
            try:
                transport = _lookup_ssh.get_transport()
                if transport and transport.is_active():
                    transport.send_ignore()
                    return _lookup_ssh
            except Exception:
                try:
                    _lookup_ssh.close()
                except Exception:
                    pass
                _lookup_ssh = None
        _lookup_ssh = _get_ssh_client()
        return _lookup_ssh


def lookup(ip_or_domain):
    """Run lookup commands on UDM Pro for a given IP or domain (parallelized)."""
    results = {}
    try:
        client = _get_or_create_lookup_ssh()

        commands = {
            "nslookup": f"nslookup {ip_or_domain} 2>&1 | head -20",
            "ipset_alien": f"ipset test ALIEN {ip_or_domain} 2>&1",
            "ipset_tor": f"ipset test TOR {ip_or_domain} 2>&1",
            "ipset_ips": f"ipset test ips {ip_or_domain} 2>&1",
            "geoip": "iptables -L UBIOS_IN_GEOIP -n -v 2>&1 | head -30",
            "conntrack": f"conntrack -L 2>&1 | grep {ip_or_domain} | head -20",
        }

        def run_cmd(key_cmd):
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
        global _lookup_ssh
        with _lookup_ssh_lock:
            _lookup_ssh = None
        results["error"] = f"SSH connection failed: {e}"

    return results


def start_log_stream(socketio, namespace, mode="all", filter_ip=None, scope="both"):
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
                    # Process lines but check stop_event between each batch
                    lines_sent = 0
                    while "\n" in buf:
                        line, buf = buf.split("\n", 1)
                        line = line.strip()
                        if line:
                            socketio.emit("log_line", {"line": line}, namespace=namespace)
                            lines_sent += 1
                        # Yield after every 10 lines so stop_stream can be processed
                        if lines_sent >= 10:
                            break
                    if lines_sent >= 10:
                        stop_event.wait(0.01)  # brief yield
                elif channel.exit_status_ready():
                    break
                else:
                    stop_event.wait(0.1)

            # Force-close transport to kill remote tcpdump/tail immediately
            try:
                transport = client.get_transport()
                if transport:
                    transport.close()
            except Exception:
                pass
            try:
                client.close()
            except Exception:
                pass
        except Exception as e:
            socketio.emit("stream_status", {"status": "error", "message": str(e)}, namespace=namespace)

        socketio.emit("stream_status", {"status": "disconnected"}, namespace=namespace)

    return stop_event, stream_worker
