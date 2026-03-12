"""Authentication blueprint: login, logout, initial setup, login_required."""
from __future__ import annotations

import hmac
import logging
import os
from functools import wraps

from flask import Blueprint, render_template, request, session, redirect, url_for
from services.audit import log_action

logger = logging.getLogger(__name__)

auth = Blueprint("auth", __name__)

# Limiter is attached after blueprint registration in app.py
_limiter = None


def set_limiter(limiter):
    global _limiter
    _limiter = limiter


def _get_pin():
    return os.environ.get("DASHBOARD_PIN", "")


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return redirect(url_for("auth.login"))
        return f(*args, **kwargs)
    return decorated


@auth.route("/initial-setup", methods=["GET", "POST"])
def initial_setup():
    from runtime import ENV_PATH
    _env_path = ENV_PATH
    if _env_path.exists() and os.environ.get("DASHBOARD_PIN", "") != "":
        return redirect(url_for("health.dashboard"))
    error = None
    if request.method == "POST":
        from services.settings import update_env_key
        from services.claude_md_generator import generate_claude_md
        pin = request.form.get("pin", "").strip()
        confirm = request.form.get("confirm_pin", "").strip()
        port = request.form.get("port", "9000").strip() or "9000"
        if not pin:
            error = "PIN is required"
        elif pin != confirm:
            error = "PINs do not match"
        else:
            if not _env_path.exists():
                _env_path.write_text("")
            update_env_key("DASHBOARD_PIN", pin)
            update_env_key("DASHBOARD_PORT", port)
            update_env_key("_DEFAULTS_MIGRATED", "1")
            try:
                generate_claude_md()
            except Exception as e:
                logger.debug("Failed to generate CLAUDE.md during setup: %s", e)
            session["authenticated"] = True
            session.permanent = True
            running_port = request.host.split(":")[-1] if ":" in request.host else "80"
            if port != running_port:
                return redirect(url_for("auth.restarting_page", port=port, next="/settings?welcome=1"))
            return redirect(url_for("settings_bp.settings_page") + "?welcome=1")
    return render_template("initial_setup.html", error=error)


@auth.route("/restarting")
@login_required
def restarting_page():
    new_port = request.args.get("port", "")
    next_url = request.args.get("next", "/")
    return render_template("restarting.html", new_port=new_port, next_url=next_url)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if session.get("authenticated"):
        return redirect(url_for("health.dashboard"))
    error = None
    if request.method == "POST":
        pin = request.form.get("pin", "")
        if hmac.compare_digest(pin, _get_pin()):
            session["authenticated"] = True
            session.permanent = True
            logger.info("Login success from %s", request.remote_addr)
            log_action("login_success", request.remote_addr)
            return redirect(request.args.get("next") or url_for("health.dashboard"))
        logger.warning("Failed login attempt from %s", request.remote_addr)
        log_action("login_failure", request.remote_addr)
        error = "Incorrect PIN"
    return render_template("login.html", error=error)


@auth.route("/logout")
def logout():
    log_action("logout", request.remote_addr)
    session.clear()
    return redirect(url_for("auth.login"))
