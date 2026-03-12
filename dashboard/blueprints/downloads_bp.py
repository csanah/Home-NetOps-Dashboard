"""Downloads blueprint: SABnzbd, Sonarr, Radarr, Prowlarr."""
from __future__ import annotations

import logging
import os

from flask import Blueprint, render_template, jsonify

from blueprints.auth import login_required

logger = logging.getLogger(__name__)

downloads_bp = Blueprint("downloads_bp", __name__)


@downloads_bp.route("/downloads")
@login_required
def downloads_page():
    return render_template("downloads.html")


@downloads_bp.route("/downloads/partials")
@login_required
def downloads_partials():
    from services.downloads import get_downloads_data
    try:
        data = get_downloads_data()
    except Exception:
        logger.exception("Failed to fetch downloads data")
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


@downloads_bp.route("/downloads/setup", methods=["POST"])
@login_required
def downloads_setup():
    from services.downloads import get_or_retrieve_api_keys
    result = get_or_retrieve_api_keys()
    return jsonify(result)
