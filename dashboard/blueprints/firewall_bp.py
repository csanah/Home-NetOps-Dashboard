"""Firewall blueprint: page, clients, rules, lookup, WebSocket handlers."""
from __future__ import annotations

import ipaddress
import logging
import threading

from flask import Blueprint, render_template, request, jsonify
from flask_socketio import emit, disconnect

from blueprints.auth import login_required
from services.audit import log_action
from services.firewall import lookup, start_log_stream
from services.udm import get_all_clients, get_firewall_rules
from services.dns_cache import DNSCache

logger = logging.getLogger(__name__)

firewall_bp = Blueprint("firewall_bp", __name__)

# Shared state
firewall_streams = {}
_fw_streams_lock = threading.Lock()
dns_cache = DNSCache()


def _is_valid_ip(s):
    try:
        ipaddress.ip_address(s)
        return True
    except (ValueError, TypeError):
        return False


@firewall_bp.route("/firewall")
@login_required
def firewall_page():
    clients = get_all_clients()
    return render_template("firewall.html", clients=clients)


@firewall_bp.route("/firewall/clients")
@login_required
def firewall_clients():
    return jsonify(get_all_clients())


@firewall_bp.route("/firewall/rules")
@login_required
def firewall_rules():
    rules = get_firewall_rules()
    return jsonify(rules)


@firewall_bp.route("/firewall/lookup", methods=["POST"])
@login_required
def firewall_lookup():
    target = request.form.get("target", "").strip()
    if not target:
        return render_template("partials/lookup_results.html", results=None, error="No IP/domain provided")
    log_action("firewall_lookup", request.remote_addr, f"target={target}")
    results = lookup(target)
    return render_template("partials/lookup_results.html", results=results, target=target, error=None)


def register_socketio(socketio):
    """Register firewall WebSocket handlers."""
    from flask import session

    @socketio.on("connect", namespace="/firewall")
    def handle_fw_connect(auth=None):
        if not session.get("authenticated"):
            disconnect()
            return False

    @socketio.on("start_stream", namespace="/firewall")
    def handle_start_stream(data=None):
        sid = request.sid
        with _fw_streams_lock:
            if sid in firewall_streams:
                firewall_streams[sid].set()
        data = data or {}
        mode = data.get("mode", "all")
        filter_ip = data.get("filter_ip") or None
        scope = data.get("scope", "both")
        stop_event, worker = start_log_stream(socketio, "/firewall", mode=mode, filter_ip=filter_ip, scope=scope)
        with _fw_streams_lock:
            firewall_streams[sid] = stop_event
        threading.Thread(target=worker, daemon=True).start()

    @socketio.on("stop_stream", namespace="/firewall")
    def handle_stop_stream():
        sid = request.sid
        with _fw_streams_lock:
            if sid in firewall_streams:
                firewall_streams[sid].set()
                del firewall_streams[sid]

    @socketio.on("disconnect", namespace="/firewall")
    def handle_fw_disconnect():
        sid = request.sid
        with _fw_streams_lock:
            if sid in firewall_streams:
                firewall_streams[sid].set()
                del firewall_streams[sid]

    @socketio.on("resolve_ips", namespace="/firewall")
    def handle_resolve_ips(data):
        ips = data.get("ips", [])[:20]
        def make_callback():
            def on_resolved(resolved_ip, hostname):
                logger.debug("DNS resolved %s -> %s", resolved_ip, hostname)
                socketio.emit("dns_result",
                              {"ip": resolved_ip, "hostname": hostname},
                              namespace="/firewall")
            return on_resolved
        cb = make_callback()
        for ip in ips:
            if not isinstance(ip, str) or not _is_valid_ip(ip):
                continue
            if not dns_cache.is_external(ip):
                continue
            dns_cache.lookup(ip, cb)
