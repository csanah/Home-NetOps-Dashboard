"""Shared middleware: CSRF, CSP, security headers, context processors."""
from __future__ import annotations

import base64
import hmac
import ipaddress
import logging
import os
import secrets
import time
import uuid
from urllib.parse import urlparse

from flask import Flask, g, jsonify, request, session, redirect, url_for
from services.correlation import set_correlation_id, clear_correlation_id
from services.metrics import metrics

logger = logging.getLogger(__name__)


def _cors_origin_check(origin):
    """Allow configured LAN subnet, localhost, and same-origin requests.

    None origin is allowed because WebSocket upgrade requests from the same
    origin don't send an Origin header. Real cross-origin protection is
    provided by CSRF tokens on state-changing requests.
    """
    if not origin:
        return True

    # Parse the origin to extract the hostname
    try:
        parsed = urlparse(origin.lower())
        host = parsed.hostname or ""
    except Exception:
        return False

    # Always allow localhost
    if host in ("localhost", "127.0.0.1", "::1"):
        return True

    # Check against configured subnet (default: 192.168.0.0/16)
    allowed_subnet = os.environ.get("CORS_ALLOWED_SUBNET", "192.168.0.0/16")
    try:
        addr = ipaddress.ip_address(host)
        network = ipaddress.ip_network(allowed_subnet, strict=False)
        return addr in network
    except ValueError:
        return False


def _is_first_run(env_path):
    return not env_path.exists() or os.environ.get("DASHBOARD_PIN", "") == ""


def _get_csrf_token():
    """Get or generate a CSRF token for the current session."""
    if "csrf_token" not in session:
        session["csrf_token"] = secrets.token_hex(32)
    return session["csrf_token"]


def init_middleware(app: Flask, env_path) -> None:
    """Register all before/after request hooks and context processors."""

    @app.before_request
    def set_request_correlation_id():
        cid = uuid.uuid4().hex[:8]
        set_correlation_id(cid)
        g.correlation_id = cid
        g.request_start_time = time.time()

    @app.before_request
    def generate_csp_nonce():
        g.csp_nonce = base64.b64encode(os.urandom(16)).decode("ascii")

    @app.before_request
    def check_first_run():
        if _is_first_run(env_path) and request.endpoint not in (
            "auth.initial_setup", "auth.restarting_page", "settings_bp.api_restart", "static"
        ):
            return redirect(url_for("auth.initial_setup"))

    @app.before_request
    def csrf_protect():
        """Validate CSRF token on state-changing requests."""
        if request.method in ("GET", "HEAD", "OPTIONS"):
            return
        if request.endpoint in ("auth.login", "auth.initial_setup", "csp_report", None):
            return
        if request.endpoint == "static":
            return
        token = request.headers.get("X-CSRFToken") or request.form.get("csrf_token")
        if not token or not hmac.compare_digest(token, session.get("csrf_token", "")):
            logger.warning(
                "CSRF check failed for %s %s from %s",
                request.method, request.path, request.remote_addr,
            )
            return jsonify({"error": "CSRF token missing or invalid"}), 403

    @app.after_request
    def log_request_and_headers(response):
        # Track request duration
        start = getattr(g, "request_start_time", None)
        if start is not None:
            duration_ms = (time.time() - start) * 1000
            metrics.observe("request.duration_ms", duration_ms)
            metrics.increment("request.count")
            logger.debug("[%s] %s %s %s %.0fms",
                         getattr(g, "correlation_id", "-"),
                         request.method, request.path, response.status_code, duration_ms)
        else:
            logger.debug("%s %s %s", request.method, request.path, response.status_code)
        nonce = getattr(g, "csp_nonce", "")
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "script-src 'self' 'nonce-{nonce}'; "
            "style-src 'self' 'unsafe-inline'; "
            "connect-src 'self' ws://192.168.* ws://localhost:*; "
            "img-src 'self' data:; "
            "font-src 'self'; "
            "report-uri /csp-report"
        ).format(nonce=nonce)
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=(), payment=()"
        )
        clear_correlation_id()
        return response

    @app.route("/csp-report", methods=["POST"])
    def csp_report():
        """Receive and log CSP violation reports."""
        try:
            report = request.get_json(force=True, silent=True) or {}
            violation = report.get("csp-report", report)
            logger.warning(
                "CSP violation: directive=%s blocked=%s source=%s",
                violation.get("violated-directive", "?"),
                violation.get("blocked-uri", "?"),
                violation.get("source-file", "?"),
            )
        except Exception:
            pass
        return "", 204

    @app.context_processor
    def inject_csp_nonce():
        return {"csp_nonce": getattr(g, "csp_nonce", "")}

    @app.context_processor
    def inject_csrf_token():
        return {"csrf_token": _get_csrf_token()}

    @app.context_processor
    def inject_display_names():
        chat_enabled = os.environ.get("CLAUDE_CHAT_ENABLED", "false").lower() == "true"
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
            "firewall_enabled": os.environ.get("SHOW_FIREWALL", "false").lower() == "true",
            "chat_enabled": chat_enabled,
            "downloads_enabled": os.environ.get("SHOW_DOWNLOADS", "false").lower() == "true",
            "plex_enabled": plex_enabled,
            "overseerr_enabled": overseerr_enabled,
            "show_sparklines": os.environ.get("SHOW_SPARKLINES", "true").lower() == "true",
            "card_visibility": {
                "media_center": os.environ.get("SHOW_MEDIA_CENTER", "false").lower() == "true",
                "udm": os.environ.get("SHOW_UDM", "false").lower() == "true",
                "proxmox": os.environ.get("SHOW_PROXMOX", "false").lower() == "true",
                "ha": os.environ.get("SHOW_HA", "false").lower() == "true",
                "nas": os.environ.get("SHOW_NAS", "false").lower() == "true",
                "mqtt": os.environ.get("SHOW_MQTT", "false").lower() == "true",
            },
        }
