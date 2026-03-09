import os
import sys
import subprocess
from pathlib import Path
from functools import wraps

# Load .env from parent directory
from dotenv import load_dotenv
load_dotenv(Path(__file__).resolve().parent.parent / ".env")

import threading

from flask import Flask, render_template, request, jsonify, session, redirect, url_for
from flask_socketio import SocketIO, emit, disconnect

import re

from services.dashboard import get_all_health, get_alerts, get_health_history
from services.firewall import lookup, start_log_stream
from services.udm import get_clients, get_all_clients, get_firewall_rules, format_rate
from services.claude_relay import ClaudeSession
from services.dns_cache import DNSCache

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("DASHBOARD_SECRET", os.urandom(24).hex())
app.config["SESSION_COOKIE_HTTPONLY"] = True
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins="*")

_env_path = Path(__file__).resolve().parent.parent / ".env"


def _is_first_run():
    return not _env_path.exists() or os.environ.get("DASHBOARD_PIN", "") == ""


@app.before_request
def check_first_run():
    if _is_first_run() and request.endpoint not in ('setup_page', 'setup_save', 'setup_test_save', 'settings_test', 'static'):
        return redirect(url_for('setup_page'))


@app.context_processor
def inject_display_names():
    chat_enabled = os.environ.get("CLAUDE_CHAT_ENABLED", "true").lower() != "false"
    plex_enabled = os.environ.get("PLEX_ENABLED", "false").lower() == "true"
    overseerr_enabled = os.environ.get("OVERSEERR_ENABLED", "false").lower() == "true"
    return {
        "names": {
            "firewall": os.environ.get("NAME_FIREWALL", "Firewall"),
            "chat": os.environ.get("NAME_CHAT", "Claude Chat"),
            "downloads": os.environ.get("NAME_DOWNLOADS", "Downloads"),
            "plex": os.environ.get("NAME_PLEX", "Plex"),
            "overseerr": os.environ.get("NAME_OVERSEERR", "Overseerr"),
            "media_center": os.environ.get("NAME_MEDIA_CENTER", "Media Center"),
            "udm": os.environ.get("NAME_UDM", "UDM Pro"),
            "proxmox": os.environ.get("NAME_PROXMOX", "Proxmox"),
            "ha": os.environ.get("NAME_HA", "Home Assistant"),
            "nas": os.environ.get("NAME_NAS", "Synology NAS"),
            "mqtt": os.environ.get("NAME_MQTT", "MQTT Broker"),
            "bike": os.environ.get("NAME_BIKE", "Bike Computer"),
        },
        "firewall_enabled": os.environ.get("SHOW_FIREWALL", "true").lower() != "false",
        "chat_enabled": chat_enabled,
        "downloads_enabled": os.environ.get("SHOW_DOWNLOADS", "true").lower() != "false",
        "plex_enabled": plex_enabled,
        "overseerr_enabled": overseerr_enabled,
        "card_visibility": {
            "media_center": os.environ.get("SHOW_MEDIA_CENTER", "true").lower() != "false",
            "udm":          os.environ.get("SHOW_UDM", "true").lower() != "false",
            "proxmox":      os.environ.get("SHOW_PROXMOX", "true").lower() != "false",
            "ha":           os.environ.get("SHOW_HA", "true").lower() != "false",
            "nas":          os.environ.get("SHOW_NAS", "true").lower() != "false",
            "mqtt":         os.environ.get("SHOW_MQTT", "true").lower() != "false",
        },
        "dashboard_port": os.environ.get("DASHBOARD_PORT", "7000"),
    }

def _get_pin():
    return os.environ.get("DASHBOARD_PIN", "")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated

# Track active firewall streams and claude sessions per client
firewall_streams = {}
claude_sessions = {}
dns_cache = DNSCache()

# Single global Claude chat session (persists across WebSocket reconnects)
_global_chat_session = None

IP_RE = re.compile(r'^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}$')


# ── Setup Wizard Routes ──

@app.route("/setup")
def setup_page():
    if not _is_first_run():
        return redirect(url_for("dashboard"))
    return render_template("setup.html")


@app.route("/setup/save", methods=["POST"])
def setup_save():
    from services.settings import update_env_key
    from services.claude_md_generator import generate_claude_md
    data = request.get_json() or {}
    if not data.get("DASHBOARD_PIN", "").strip():
        return jsonify({"success": False, "error": "PIN is required"})
    # Create .env if it doesn't exist
    if not _env_path.exists():
        _env_path.write_text("")
    # Write all fields
    for key, value in data.items():
        value = str(value).strip()
        if value:
            update_env_key(key, value)
    # Generate CLAUDE.md from template
    try:
        generate_claude_md()
    except Exception:
        pass
    return jsonify({"success": True})


@app.route("/setup/test-save", methods=["POST"])
def setup_test_save():
    """Temporarily save wizard fields to os.environ so test endpoints can use them."""
    data = request.get_json() or {}
    for key, value in data.items():
        value = str(value).strip()
        if value:
            os.environ[key] = value
    return jsonify({"ok": True})


# ── Auth Routes ──

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("dashboard"))
    error = None
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if pin == _get_pin():
            session["authenticated"] = True
            return redirect(request.args.get("next") or url_for("dashboard"))
        error = "Incorrect PIN"
    return render_template("login.html", error=error)


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ── Routes ──

@app.route("/")
@login_required
def dashboard():
    health = get_all_health()
    alerts = get_alerts(health)
    bandwidth = health.pop("bandwidth", [])
    udm_data = health.get("udm", {})
    wan_down = format_rate(udm_data.get("wan_down_bps", 0))
    wan_up = format_rate(udm_data.get("wan_up_bps", 0))
    history = get_health_history()
    return render_template("dashboard.html", health=health, alerts=alerts,
                           bandwidth=bandwidth, wan_down=wan_down, wan_up=wan_up,
                           history=history)


@app.route("/partials/cards")
@login_required
def partials_cards():
    health = get_all_health()
    bandwidth = health.pop("bandwidth", [])
    udm_data = health.get("udm", {})
    wan_down = format_rate(udm_data.get("wan_down_bps", 0))
    wan_up = format_rate(udm_data.get("wan_up_bps", 0))
    history = get_health_history()
    return render_template("partials/all_cards.html", health=health,
                           bandwidth=bandwidth, wan_down=wan_down, wan_up=wan_up,
                           history=history)


@app.route("/partials/alerts")
@login_required
def partials_alerts():
    health = get_all_health()
    alerts = get_alerts(health)
    return render_template("partials/alert_list.html", alerts=alerts)


@app.route("/api/health")
@login_required
def api_health():
    health = get_all_health()
    alerts = get_alerts(health)
    return jsonify({"systems": health, "alerts": alerts})


@app.route("/firewall")
@login_required
def firewall_page():
    clients = get_all_clients()
    return render_template("firewall.html", clients=clients)


@app.route("/firewall/clients")
@login_required
def firewall_clients():
    return jsonify(get_all_clients())


@app.route("/firewall/rules")
@login_required
def firewall_rules():
    rules = get_firewall_rules()
    return jsonify(rules)


@app.route("/firewall/lookup", methods=["POST"])
@login_required
def firewall_lookup():
    target = request.form.get("target", "").strip()
    if not target:
        return render_template("partials/lookup_results.html", results=None, error="No IP/domain provided")
    results = lookup(target)
    return render_template("partials/lookup_results.html", results=results, target=target, error=None)


@app.route("/chat")
@login_required
def chat_page():
    if os.environ.get("CLAUDE_CHAT_ENABLED", "true").lower() == "false":
        return redirect(url_for("settings_page"))
    return render_template("chat.html")



@app.route("/downloads")
@login_required
def downloads_page():
    return render_template("downloads.html")


@app.route("/downloads/partials")
@login_required
def downloads_partials():
    from services.downloads import get_downloads_data
    try:
        data = get_downloads_data()
    except Exception:
        data = {
            "sabnzbd_queue": {"error": "Backend error"},
            "sabnzbd_history": {"error": "Backend error"},
            "sonarr_queue": {"error": "Backend error"},
            "sonarr_calendar": {"error": "Backend error"},
            "radarr_queue": {"error": "Backend error"},
            "radarr_calendar": {"error": "Backend error"},
            "has_sabnzbd_key": bool(os.environ.get("SABNZBD_API_KEY", "")),
            "has_sonarr_key": bool(os.environ.get("SONARR_API_KEY", "")),
            "has_radarr_key": bool(os.environ.get("RADARR_API_KEY", "")),
            "has_prowlarr_key": bool(os.environ.get("PROWLARR_API_KEY", "")),
        }
    return render_template("partials/downloads_cards.html", data=data)


@app.route("/downloads/setup", methods=["POST"])
@login_required
def downloads_setup():
    from services.downloads import get_or_retrieve_api_keys
    result = get_or_retrieve_api_keys()
    return jsonify(result)


@app.route("/plex")
@login_required
def plex_page():
    if os.environ.get("PLEX_ENABLED", "false").lower() != "true":
        return redirect(url_for("settings_page"))
    return render_template("plex.html")


@app.route("/plex/partials")
@login_required
def plex_partials():
    from services.plex import get_plex_data
    try:
        data = get_plex_data()
    except Exception:
        data = {
            "server": {"error": "Backend error"},
            "libraries": {"error": "Backend error"},
            "sessions": {"error": "Backend error"},
            "recently_added": {"error": "Backend error"},
            "on_deck": {"error": "Backend error"},
            "history": {"error": "Backend error"},
            "bandwidth": {"error": "Backend error"},
            "has_token": bool(os.environ.get("PLEX_TOKEN", "")),
        }
    try:
        return render_template("partials/plex_cards.html", data=data)
    except Exception as e:
        return f'<div class="p-4 text-sm text-red-400">Error rendering Plex data: {e}</div>'


@app.route("/plex/partials/sessions")
@login_required
def plex_sessions_partial():
    from services.plex import get_plex_sessions
    try:
        data = get_plex_sessions()
    except Exception:
        data = {
            "sessions": {"error": "Backend error"},
            "has_token": bool(os.environ.get("PLEX_TOKEN", "")),
        }
    try:
        return render_template("partials/plex_sessions.html", data=data)
    except Exception as e:
        return f'<div class="p-4 text-sm text-red-400">Error rendering sessions: {e}</div>'


@app.route("/plex/search")
@login_required
def plex_search():
    from services.plex import search_plex
    query = request.args.get("q", "").strip()
    if not query:
        return ""
    try:
        data = search_plex(query)
    except Exception as e:
        data = {"results": [], "query": query, "error": str(e)}
    return render_template("partials/plex_search_results.html", data=data)


@app.route("/plex/auto-detect", methods=["POST"])
@login_required
def plex_auto_detect():
    from services.settings import auto_detect_plex_token
    result = auto_detect_plex_token()
    return jsonify(result)


@app.route("/overseerr")
@login_required
def overseerr_page():
    if os.environ.get("OVERSEERR_ENABLED", "false").lower() != "true":
        return redirect(url_for("settings_page"))
    return render_template("overseerr.html")


@app.route("/overseerr/partials")
@login_required
def overseerr_partials():
    from services.overseerr import get_overseerr_data
    try:
        data = get_overseerr_data()
    except Exception:
        data = {
            "stats": {"error": "Backend error"},
            "pending": {"error": "Backend error"},
            "recent": {"error": "Backend error"},
            "trending": {"error": "Backend error"},
            "has_key": bool(os.environ.get("OVERSEERR_API_KEY", "")),
        }
    try:
        return render_template("partials/overseerr_cards.html", data=data)
    except Exception as e:
        return f'<div class="p-4 text-sm text-red-400">Error rendering Overseerr data: {e}</div>'


@app.route("/overseerr/auto-detect", methods=["POST"])
@login_required
def overseerr_auto_detect():
    from services.overseerr import auto_detect_overseerr_key
    result = auto_detect_overseerr_key()
    return jsonify(result)


@app.route("/settings")
@login_required
def settings_page():
    from services.settings import get_all_settings, SETTINGS_SCHEMA
    settings = get_all_settings()
    return render_template("settings.html", settings=settings)


@app.route("/settings/save/<section>", methods=["POST"])
@login_required
def settings_save(section):
    from services.settings import save_section
    data = request.get_json() or {}
    result = save_section(section, data)
    return jsonify(result)


@app.route("/settings/test/<system>", methods=["POST"])
@login_required
def settings_test(system):
    from services.settings import test_connection
    result = test_connection(system)
    return jsonify(result)


@app.route("/settings/auto-detect-keys", methods=["POST"])
@login_required
def settings_auto_detect():
    from services.settings import auto_detect_media_keys
    result = auto_detect_media_keys()
    return jsonify(result)


def kill_port_holders(port=7000, exclude_pid=None):
    """Kill any process listening on the given port (Windows netstat + taskkill).
    Excludes exclude_pid (defaults to current process) to avoid self-kill."""
    if exclude_pid is None:
        exclude_pid = os.getpid()
    try:
        out = subprocess.check_output(
            ["netstat", "-ano", "-p", "TCP"],
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            text=True, timeout=5,
        )
        pids = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and f":{port}" in parts[1] and parts[3] == "LISTENING":
                pid = int(parts[4])
                if pid != exclude_pid and pid != 0:
                    pids.add(pid)
        for pid in pids:
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                capture_output=True, timeout=5,
            )
    except Exception:
        pass


@app.route("/api/restart", methods=["POST"])
@login_required
def api_restart():
    """Restart the dashboard server. Kills stale instances, spawns new, then exits."""
    python = sys.executable
    script = os.path.abspath(__file__)
    my_pid = os.getpid()
    def _restart():
        import time
        time.sleep(1)
        # Kill any stale python instances on our port (except ourselves)
        kill_port_holders(exclude_pid=my_pid)
        subprocess.Popen(
            [python, script],
            cwd=os.path.dirname(script),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        os._exit(0)
    threading.Thread(target=_restart, daemon=True).start()
    return jsonify({"status": "restarting"})


# ── Firewall WebSocket ──

@socketio.on("connect", namespace="/firewall")
def handle_fw_connect(auth=None):
    if not session.get("authenticated"):
        disconnect()
        return False


@socketio.on("start_stream", namespace="/firewall")
def handle_start_stream(data=None):
    sid = request.sid
    if sid in firewall_streams:
        firewall_streams[sid].set()
    data = data or {}
    mode = data.get("mode", "all")
    filter_ip = data.get("filter_ip") or None
    scope = data.get("scope", "both")
    stop_event, worker = start_log_stream(socketio, "/firewall", mode=mode, filter_ip=filter_ip, scope=scope)
    firewall_streams[sid] = stop_event
    threading.Thread(target=worker, daemon=True).start()


@socketio.on("stop_stream", namespace="/firewall")
def handle_stop_stream():
    sid = request.sid
    if sid in firewall_streams:
        firewall_streams[sid].set()
        del firewall_streams[sid]


@socketio.on("disconnect", namespace="/firewall")
def handle_fw_disconnect():
    sid = request.sid
    if sid in firewall_streams:
        firewall_streams[sid].set()
        del firewall_streams[sid]


@socketio.on("resolve_ips", namespace="/firewall")
def handle_resolve_ips(data):
    ips = data.get("ips", [])[:20]  # cap at 20 per batch
    def make_callback():
        def on_resolved(resolved_ip, hostname):
            print(f"[DNS] {resolved_ip} -> {hostname}")
            socketio.emit("dns_result",
                          {"ip": resolved_ip, "hostname": hostname},
                          namespace="/firewall")
        return on_resolved
    cb = make_callback()
    for ip in ips:
        if not isinstance(ip, str) or not IP_RE.match(ip):
            continue
        if not dns_cache.is_external(ip):
            continue
        dns_cache.lookup(ip, cb)


# ── Claude Chat WebSocket ──

def _get_chat_session():
    """Get or create the global chat session."""
    global _global_chat_session
    if _global_chat_session is None:
        _global_chat_session = ClaudeSession(socketio, "/chat")
        _global_chat_session.start()
    return _global_chat_session


@socketio.on("connect", namespace="/chat")
def handle_chat_connect(auth=None):
    if not session.get("authenticated"):
        disconnect()
        return False
    if os.environ.get("CLAUDE_CHAT_ENABLED", "true").lower() == "false":
        disconnect()
        return False


@socketio.on("start_session", namespace="/chat")
def handle_start_session():
    sid = request.sid
    chat = _get_chat_session()
    chat.add_client(sid)
    # Send session status
    emit("session_status", {"status": "started"})
    # Replay persisted history
    history = chat.get_history()
    if history:
        emit("history_replay", {"messages": history})
    # If generation is in progress, let client know and flush buffered output
    if chat.generating:
        emit("generation_started")
        chat.flush_buffer(sid)


@socketio.on("send_message", namespace="/chat")
def handle_send_message(data):
    chat = _get_chat_session()
    message = data.get("message", "")
    chat.send(message)


@socketio.on("cancel_generation", namespace="/chat")
def handle_cancel_generation():
    chat = _get_chat_session()
    chat.cancel()


@socketio.on("set_mode", namespace="/chat")
def handle_set_mode(data):
    chat = _get_chat_session()
    mode = data.get("mode", "general")
    chat.set_mode(mode)


@socketio.on("clear_history", namespace="/chat")
def handle_clear_history():
    chat = _get_chat_session()
    chat.clear()


@socketio.on("stop_session", namespace="/chat")
def handle_stop_session():
    chat = _get_chat_session()
    chat.cancel()  # Cancel current generation but keep session alive


@socketio.on("disconnect", namespace="/chat")
def handle_chat_disconnect():
    sid = request.sid
    if _global_chat_session is not None:
        _global_chat_session.remove_client(sid)


if __name__ == "__main__":
    port = int(os.environ.get("DASHBOARD_PORT", "7000"))
    socketio.run(app, host="0.0.0.0", port=port, debug=False, allow_unsafe_werkzeug=True)
