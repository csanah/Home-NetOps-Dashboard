"""Plex blueprint: Plex Media Server integration."""
from __future__ import annotations

import logging
import os

from flask import Blueprint, render_template, redirect, url_for, request, jsonify

from blueprints.auth import login_required

logger = logging.getLogger(__name__)

plex_bp = Blueprint("plex_bp", __name__)


@plex_bp.route("/plex")
@login_required
def plex_page():
    if os.environ.get("PLEX_ENABLED", "false").lower() != "true":
        return redirect(url_for("settings_bp.settings_page"))
    return render_template("plex.html")


@plex_bp.route("/plex/partials")
@login_required
def plex_partials():
    from services.plex import get_plex_data
    try:
        data = get_plex_data()
    except Exception:
        logger.exception("Failed to fetch Plex data")
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
        return render_template("partials/error_inline.html", error=str(e))


@plex_bp.route("/plex/partials/sessions")
@login_required
def plex_sessions_partial():
    from services.plex import get_plex_sessions
    try:
        data = get_plex_sessions()
    except Exception:
        logger.exception("Failed to fetch Plex sessions")
        data = {
            "sessions": {"error": "Backend error"},
            "has_token": bool(os.environ.get("PLEX_TOKEN", "")),
        }
    try:
        return render_template("partials/plex_sessions.html", data=data)
    except Exception as e:
        return render_template("partials/error_inline.html", error=str(e))


@plex_bp.route("/plex/search")
@login_required
def plex_search():
    from services.plex import search_plex
    from services.validators import sanitize_search_query
    query = sanitize_search_query(request.args.get("q", "").strip())
    if not query:
        return ""
    try:
        data = search_plex(query)
    except Exception as e:
        data = {"results": [], "query": query, "error": str(e)}
    return render_template("partials/plex_search_results.html", data=data)


@plex_bp.route("/plex/auto-detect", methods=["POST"])
@login_required
def plex_auto_detect():
    from services.settings import auto_detect_plex_token
    result = auto_detect_plex_token()
    return jsonify(result)
