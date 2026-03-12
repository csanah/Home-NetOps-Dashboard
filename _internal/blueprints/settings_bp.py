"""Settings blueprint: configuration, connection tests, export, restart."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
import threading

from flask import Blueprint, render_template, request, jsonify, send_file

from blueprints.auth import login_required
from services.audit import log_action

logger = logging.getLogger(__name__)

settings_bp = Blueprint("settings_bp", __name__)

# Set by app factory
_frozen = False


def set_frozen(frozen: bool) -> None:
    global _frozen
    _frozen = frozen


@settings_bp.route("/settings")
@login_required
def settings_page():
    from flask import current_app
    from services.settings import get_all_settings
    settings = get_all_settings()
    return render_template(
        "settings.html",
        settings=settings,
        cli_detected=current_app.config.get("CLAUDE_CLI_DETECTED", False),
        cli_path=current_app.config.get("CLAUDE_CLI_PATH", ""),
    )


@settings_bp.route("/settings/save/<section>", methods=["POST"])
@login_required
def settings_save(section):
    from services.settings import save_section
    from services.validators import validate_section_id, validate_settings_values
    if not validate_section_id(section):
        return jsonify({"success": False, "error": "Unknown section"}), 400
    data = request.get_json() or {}
    validation_error = validate_settings_values(section, data)
    if validation_error:
        return jsonify({"success": False, **validation_error}), 400
    result = save_section(section, data)
    log_action("settings_save", request.remote_addr, f"section={section}")
    return jsonify(result)


@settings_bp.route("/settings/test/<system>", methods=["POST"])
@login_required
def settings_test(system):
    from services.settings import test_connection
    from services.validators import validate_system_id
    if not validate_system_id(system):
        return jsonify({"success": False, "message": f"Unknown system: {system}"}), 400
    result = test_connection(system)
    log_action("connection_test", request.remote_addr, f"system={system}")
    return jsonify(result)


@settings_bp.route("/settings/auto-detect-keys", methods=["POST"])
@login_required
def settings_auto_detect():
    from services.settings import auto_detect_media_keys
    result = auto_detect_media_keys()
    return jsonify(result)


@settings_bp.route("/settings/export/env")
@login_required
def export_env():
    from runtime import ENV_PATH
    return send_file(str(ENV_PATH), as_attachment=True, download_name=".env")


@settings_bp.route("/settings/export/claude-md")
@login_required
def export_claude_md():
    from runtime import PROJECT_ROOT
    claude_path = PROJECT_ROOT / "CLAUDE.md"
    return send_file(str(claude_path), as_attachment=True, download_name="CLAUDE.md")


def kill_port_holders(port=9000, exclude_pid=None):
    """Kill any process listening on the given port."""
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
    except Exception as e:
        logger.debug("kill_port_holders failed: %s", e)


@settings_bp.route("/api/restart", methods=["POST"])
@login_required
def api_restart():
    """Restart the dashboard server."""
    def _restart():
        import time
        time.sleep(1)
        if _frozen:
            try:
                import win32serviceutil
                win32serviceutil.RestartService("SystemControlDashboard")
                return
            except Exception:
                pass
        python = sys.executable
        script = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "app.py"))
        kill_port_holders(exclude_pid=os.getpid())
        subprocess.Popen(
            [python, script],
            cwd=os.path.dirname(script),
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
        os._exit(0)
    threading.Thread(target=_restart, daemon=True).start()
    return jsonify({"status": "restarting"})
