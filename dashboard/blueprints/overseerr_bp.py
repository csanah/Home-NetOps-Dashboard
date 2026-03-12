"""Overseerr blueprint: media request management."""
from __future__ import annotations

import logging
import os

from flask import Blueprint, render_template, redirect, url_for, jsonify

from blueprints.auth import login_required

logger = logging.getLogger(__name__)

overseerr_bp = Blueprint("overseerr_bp", __name__)


@overseerr_bp.route("/overseerr")
@login_required
def overseerr_page():
    if os.environ.get("OVERSEERR_ENABLED", "false").lower() != "true":
        return redirect(url_for("settings_bp.settings_page"))
    return render_template("overseerr.html")


@overseerr_bp.route("/overseerr/partials")
@login_required
def overseerr_partials():
    from services.overseerr import get_overseerr_data
    try:
        data = get_overseerr_data()
    except Exception:
        logger.exception("Failed to fetch Overseerr data")
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
        return render_template("partials/error_inline.html", error=str(e))


@overseerr_bp.route("/overseerr/auto-detect", methods=["POST"])
@login_required
def overseerr_auto_detect():
    from services.overseerr import auto_detect_overseerr_key
    result = auto_detect_overseerr_key()
    return jsonify(result)
