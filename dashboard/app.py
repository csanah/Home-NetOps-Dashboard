"""Dashboard application factory — registers blueprints, middleware, and WebSocket handlers."""
import logging
import logging.handlers
import os
import sys
from datetime import datetime

_start_time = datetime.now()

from runtime import ENV_PATH, LOG_DIR, APP_DIR, FROZEN, TEMPLATE_DIR, STATIC_DIR

# Load .env
from dotenv import load_dotenv
load_dotenv(ENV_PATH)

from flask import Flask
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# ── Structured Logging ──
_log_file = LOG_DIR / "dashboard.log"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s [%(correlation_id)s]: %(message)s",
    handlers=[
        logging.handlers.RotatingFileHandler(
            _log_file, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
        ),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("paramiko").setLevel(logging.WARNING)
logging.getLogger("engineio").setLevel(logging.WARNING)
logging.getLogger("socketio").setLevel(logging.WARNING)

from services.correlation import CorrelationFilter

_corr_filter = CorrelationFilter()
for _handler in logging.root.handlers:
    _handler.addFilter(_corr_filter)

# ── App & Extensions ──
if FROZEN:
    app = Flask(__name__,
                template_folder=str(TEMPLATE_DIR),
                static_folder=str(STATIC_DIR))
else:
    app = Flask(__name__)


def _get_or_create_secret_key():
    """Return a persistent secret key: env var > file > generate-and-save."""
    key = os.environ.get("DASHBOARD_SECRET")
    if key:
        return key
    key_file = LOG_DIR / ".secret_key"
    try:
        if key_file.exists():
            return key_file.read_text().strip()
    except (IOError, OSError) as e:
        logger.debug("Could not read secret key file: %s", e)
    key = os.urandom(24).hex()
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        key_file.write_text(key)
    except (IOError, OSError) as e:
        logger.debug("Could not persist secret key: %s", e)
    return key


app.config["SECRET_KEY"] = _get_or_create_secret_key()
app.config["SESSION_COOKIE_HTTPONLY"] = True
app.config["SESSION_COOKIE_SAMESITE"] = "Lax"
app.config["PERMANENT_SESSION_LIFETIME"] = 3600

from middleware import _cors_origin_check, init_middleware

# ── WebSocket Transport ──
# Uses async_mode="threading" with simple-websocket for proper WebSocket support.
#
# Why not alternatives:
#   - eventlet: greenlet C-extension has DLL/ABI issues on Windows + Python 3.12
#   - gevent: libev/libuv C-extensions also fail on Windows + Python 3.12
#   - Waitress: HTTP-only server, no WebSocket support
#
# simple-websocket is Flask-SocketIO's recommended transport for threading mode.
socketio = SocketIO(app, async_mode="threading", cors_allowed_origins=_cors_origin_check)

# ── Rate Limiting ──
limiter = Limiter(
    get_remote_address,
    app=app,
    default_limits=[],
    storage_uri="memory://",
)

# ── Middleware ──
_env_path = ENV_PATH
init_middleware(app, _env_path)

# ── Defaults Migration ──
def _migrate_defaults():
    """For existing installs, explicitly write all SHOW_* toggles as 'true' so
    flipping the schema defaults to 'false' doesn't hide already-configured features."""
    if not _env_path.exists():
        return
    if not os.environ.get("DASHBOARD_PIN", ""):
        return
    if os.environ.get("_DEFAULTS_MIGRATED", "") == "1":
        return

    from services.settings import update_env_key
    toggles = [
        "SHOW_MEDIA_CENTER", "SHOW_UDM", "SHOW_PROXMOX", "SHOW_HA",
        "SHOW_NAS", "SHOW_MQTT", "CLAUDE_CHAT_ENABLED", "SHOW_FIREWALL",
        "SHOW_DOWNLOADS", "SHOW_SPARKLINES",
    ]
    env_text = _env_path.read_text()
    for key in toggles:
        if not any(line.startswith(f"{key}=") for line in env_text.splitlines()):
            update_env_key(key, "true")
    update_env_key("_DEFAULTS_MIGRATED", "1")


_migrate_defaults()


# ── Claude CLI Auto-Detection ──
def _auto_detect_claude_cli():
    """Check if Claude CLI exists; auto-disable chat if not found and not explicitly set."""
    from services.claude_relay import detect_claude_cli
    result = detect_claude_cli()
    app.config["CLAUDE_CLI_DETECTED"] = result["found"]
    app.config["CLAUDE_CLI_PATH"] = result["path"]

    if not result["found"]:
        # Check if user explicitly set CLAUDE_CHAT_ENABLED in .env
        explicitly_set = False
        try:
            env_text = ENV_PATH.read_text()
            explicitly_set = any(
                line.startswith("CLAUDE_CHAT_ENABLED=")
                for line in env_text.splitlines()
            )
        except (IOError, OSError):
            pass

        if not explicitly_set:
            os.environ["CLAUDE_CHAT_ENABLED"] = "false"
            logger.info("Claude CLI not found at %s — chat auto-disabled", result["path"])
        else:
            logger.warning(
                "Claude CLI not found at %s but CLAUDE_CHAT_ENABLED is explicitly set",
                result["path"],
            )
    else:
        logger.info("Claude CLI detected at %s", result["path"])


_auto_detect_claude_cli()

# ── Register Blueprints ──
from blueprints.auth import auth, set_limiter
from blueprints.health import health, set_start_time
from blueprints.firewall_bp import firewall_bp, register_socketio as register_fw_socketio
from blueprints.chat_bp import chat_bp, register_socketio as register_chat_socketio
from blueprints.downloads_bp import downloads_bp
from blueprints.plex_bp import plex_bp
from blueprints.overseerr_bp import overseerr_bp
from blueprints.settings_bp import settings_bp, set_frozen

# Configure blueprint dependencies
set_limiter(limiter)
set_start_time(_start_time)
set_frozen(FROZEN)

# Apply rate limiting to auth blueprint login
limiter.limit("5/minute", methods=["POST"])(
    auth.view_functions.get("login", lambda: None)
)
# Apply rate limiting to settings save
limiter.limit("10/minute")(
    settings_bp.view_functions.get("settings_save", lambda: None)
)

app.register_blueprint(auth)
app.register_blueprint(health)
app.register_blueprint(firewall_bp)
app.register_blueprint(chat_bp)
app.register_blueprint(downloads_bp)
app.register_blueprint(plex_bp)
app.register_blueprint(overseerr_bp)
app.register_blueprint(settings_bp)

# ── Register WebSocket Handlers ──
register_fw_socketio(socketio)
register_chat_socketio(socketio)

# ── Backward-Compat Aliases ──
# Some tests and imports reference these directly from app module
from blueprints.auth import login_required
from services.dashboard import get_all_health, get_alerts, get_health_history
from services.firewall import lookup
from services.udm import format_rate

# ── Startup Validation & Shutdown ──
from services.startup import validate_env, validate_dependencies
from services.shutdown import register_shutdown
register_shutdown()

if __name__ == "__main__":
    validate_env()
    validate_dependencies()
    port = int(os.environ.get("DASHBOARD_PORT", "9000"))
    logger.info("Starting dashboard on port %d", port)
    socketio.run(app, host="0.0.0.0", port=port, debug=False)
