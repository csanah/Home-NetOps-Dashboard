"""Claude Chat blueprint: chat page and WebSocket handlers."""
from __future__ import annotations

import logging
import os
import threading

from flask import Blueprint, render_template, redirect, url_for, request
from flask_socketio import emit, disconnect

from blueprints.auth import login_required
from services.claude_relay import ClaudeSession

logger = logging.getLogger(__name__)

chat_bp = Blueprint("chat_bp", __name__)

# Single global Claude chat session (persists across WebSocket reconnects)
_global_chat_session = None
_chat_session_lock = threading.Lock()


def _get_chat_session(socketio):
    """Get or create the global chat session (thread-safe)."""
    global _global_chat_session
    if _global_chat_session is not None:
        return _global_chat_session
    with _chat_session_lock:
        if _global_chat_session is None:
            _global_chat_session = ClaudeSession(socketio, "/chat")
            _global_chat_session.start()
        return _global_chat_session


def kill_chat_session():
    """Stop and discard the global chat session (thread-safe)."""
    global _global_chat_session
    with _chat_session_lock:
        if _global_chat_session is not None:
            try:
                _global_chat_session.stop()
            except Exception as e:
                logger.debug("Error stopping chat session: %s", e)
            _global_chat_session = None


@chat_bp.route("/chat")
@login_required
def chat_page():
    if os.environ.get("CLAUDE_CHAT_ENABLED", "false").lower() != "true":
        return redirect(url_for("settings_bp.settings_page"))
    return render_template("chat.html")


def register_socketio(socketio):
    """Register chat WebSocket handlers."""
    from flask import session

    @socketio.on("connect", namespace="/chat")
    def handle_chat_connect(auth=None):
        if not session.get("authenticated"):
            disconnect()
            return False
        if os.environ.get("CLAUDE_CHAT_ENABLED", "false").lower() != "true":
            disconnect()
            return False

    @socketio.on("start_session", namespace="/chat")
    def handle_start_session():
        sid = request.sid
        chat = _get_chat_session(socketio)
        chat.add_client(sid)
        emit("session_status", {"status": "started"})
        history = chat.get_history()
        if history:
            emit("history_replay", {"messages": history})
        if chat.generating:
            emit("generation_started")
            chat.flush_buffer(sid)

    @socketio.on("send_message", namespace="/chat")
    def handle_send_message(data):
        chat = _get_chat_session(socketio)
        message = data.get("message", "")
        chat.send(message)

    @socketio.on("cancel_generation", namespace="/chat")
    def handle_cancel_generation():
        chat = _get_chat_session(socketio)
        chat.cancel()

    @socketio.on("set_mode", namespace="/chat")
    def handle_set_mode(data):
        chat = _get_chat_session(socketio)
        mode = data.get("mode", "general")
        chat.set_mode(mode)

    @socketio.on("clear_history", namespace="/chat")
    def handle_clear_history():
        chat = _get_chat_session(socketio)
        chat.clear()

    @socketio.on("stop_session", namespace="/chat")
    def handle_stop_session():
        chat = _get_chat_session(socketio)
        chat.cancel()

    @socketio.on("disconnect", namespace="/chat")
    def handle_chat_disconnect():
        sid = request.sid
        if _global_chat_session is not None:
            _global_chat_session.remove_client(sid)
