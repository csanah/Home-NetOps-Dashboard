"""Health/dashboard blueprint: main dashboard, cards, alerts, API health."""
from __future__ import annotations

import logging
import os
import threading
from datetime import datetime

from flask import Blueprint, render_template, jsonify

from blueprints.auth import login_required
from services.dashboard import get_all_health, get_alerts, get_health_history
from services.udm import format_rate

logger = logging.getLogger(__name__)

health = Blueprint("health", __name__)

# Set by app factory
_start_time = None


def set_start_time(t: datetime) -> None:
    global _start_time
    _start_time = t


@health.route("/")
@login_required
def dashboard():
    data = get_all_health()
    alerts = get_alerts(data)
    bandwidth = data.pop("bandwidth", [])
    udm_data = data.get("udm", {})
    wan_down = format_rate(udm_data.get("wan_down_bps", 0))
    wan_up = format_rate(udm_data.get("wan_up_bps", 0))
    history = get_health_history()
    return render_template("dashboard.html", health=data, alerts=alerts,
                           bandwidth=bandwidth, wan_down=wan_down, wan_up=wan_up,
                           history=history)


@health.route("/partials/cards")
@login_required
def partials_cards():
    from flask import current_app
    data = get_all_health()
    bandwidth = data.pop("bandwidth", [])
    udm_data = data.get("udm", {})
    wan_down = format_rate(udm_data.get("wan_down_bps", 0))
    wan_up = format_rate(udm_data.get("wan_up_bps", 0))
    history = get_health_history()
    resp = current_app.make_response(render_template("partials/all_cards.html", health=data,
                           bandwidth=bandwidth, wan_down=wan_down, wan_up=wan_up,
                           history=history))
    resp.headers["Cache-Control"] = "private, max-age=15"
    return resp


@health.route("/partials/alerts")
@login_required
def partials_alerts():
    from flask import current_app
    data = get_all_health()
    alerts = get_alerts(data)
    resp = current_app.make_response(render_template("partials/alert_list.html", alerts=alerts))
    resp.headers["Cache-Control"] = "private, max-age=15"
    return resp


@health.route("/api/health")
@login_required
def api_health():
    import psutil
    from services.dashboard import _circuit_state, _circuit_lock

    data = get_all_health()
    alerts = get_alerts(data)

    process = psutil.Process()
    uptime = (datetime.now() - _start_time).total_seconds()

    with _circuit_lock:
        breakers = {
            k: {"failures": v["failures"], "open": v["failures"] >= 3}
            for k, v in _circuit_state.items()
        }

    from services.metrics import metrics
    return jsonify({
        "status": "ok",
        "uptime_seconds": int(uptime),
        "uptime_human": str(datetime.now() - _start_time).split(".")[0],
        "memory_mb": round(process.memory_info().rss / 1024 / 1024, 1),
        "active_threads": threading.active_count(),
        "circuit_breakers": breakers,
        "systems": data,
        "alerts": alerts,
        "metrics": metrics.snapshot(),
    })
