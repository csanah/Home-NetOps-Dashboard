import os
import re
import threading
import time
import socket
from pathlib import Path

import paramiko
import requests

from runtime import ENV_PATH
_env_lock = threading.Lock()

# Schema: section -> list of field dicts
SETTINGS_SCHEMA = {
    "layout": {
        "title": "Show Dashboard Cards",
        "color": "teal",
        "fields": [
            {"key": "SHOW_MEDIA_CENTER", "label": "Media Center",    "type": "checkbox", "default": "false"},
            {"key": "SHOW_UDM",          "label": "UDM Pro",          "type": "checkbox", "default": "false"},
            {"key": "SHOW_PROXMOX",      "label": "Proxmox",          "type": "checkbox", "default": "false"},
            {"key": "SHOW_HA",           "label": "Home Assistant",    "type": "checkbox", "default": "false"},
            {"key": "SHOW_NAS",          "label": "Synology NAS",      "type": "checkbox", "default": "false"},
            {"key": "SHOW_MQTT",         "label": "MQTT Broker",       "type": "checkbox", "default": "false"},
            {"key": "SHOW_SPARKLINES",  "label": "Sparklines",        "type": "checkbox", "default": "false"},
        ],
        "tests": [],
    },
    "claude_chat": {
        "title": "Claude Chat",
        "color": "violet",
        "fields": [
            {"key": "CLAUDE_CHAT_ENABLED", "label": "Show Chat Page", "type": "checkbox", "default": "false"},
            {"key": "NAME_CHAT", "label": "Display Name", "type": "text", "default": "Claude Chat"},
        ],
        "tests": [],
    },
    "dashboard": {
        "title": "Dashboard",
        "color": "blue",
        "fields": [
            {"key": "DASHBOARD_PIN", "label": "PIN Code", "type": "password"},
            {"key": "DASHBOARD_PORT", "label": "Port", "type": "number", "default": "9000", "restart": True},
        ],
        "tests": [],
    },
    "udm": {
        "title": "UDM Pro",
        "color": "indigo",
        "fields": [
            {"key": "SHOW_FIREWALL", "label": "Show Firewall Page", "type": "checkbox", "default": "false"},
            {"key": "NAME_FIREWALL", "label": "Firewall Display Name", "type": "text", "default": "Firewall"},
            {"key": "NAME_UDM", "label": "Display Name", "type": "text", "default": "UDM Pro"},
            {"key": "UDM_HOST", "label": "Host", "type": "text"},
            {"key": "UDM_API_KEY", "label": "API Key", "type": "password"},
            {"key": "UDM_SSH_USER", "label": "SSH Username", "type": "text", "default": "root"},
            {"key": "UDM_SSH_PASS", "label": "SSH Password", "type": "password"},
        ],
        "tests": ["api", "ssh"],
    },
    "proxmox": {
        "title": "Proxmox",
        "color": "orange",
        "fields": [
            {"key": "NAME_PROXMOX", "label": "Display Name", "type": "text", "default": "Proxmox"},
            {"key": "PROXMOX_HOST", "label": "Host", "type": "text"},
            {"key": "PROXMOX_PORT", "label": "Port", "type": "number", "default": "8006"},
            {"key": "PROXMOX_TOKEN", "label": "API Token", "type": "password"},
            {"key": "PROXMOX_NODE", "label": "Node Name", "type": "text"},
            {"key": "PROXMOX_SSH_USER", "label": "SSH Username", "type": "text", "default": "root"},
            {"key": "PROXMOX_SSH_PASS", "label": "SSH Password", "type": "password"},
        ],
        "tests": ["api", "ssh"],
    },
    "ha": {
        "title": "Home Assistant",
        "color": "cyan",
        "fields": [
            {"key": "NAME_HA", "label": "Display Name", "type": "text", "default": "Home Assistant"},
            {"key": "NAME_MQTT", "label": "MQTT Display Name", "type": "text", "default": "MQTT Broker"},
            {"key": "HA_HOST", "label": "Host", "type": "text"},
            {"key": "HA_PORT", "label": "Port", "type": "number", "default": "8123"},
            {"key": "HA_TOKEN", "label": "Bearer Token", "type": "password"},
        ],
        "tests": ["api"],
    },
    "nas": {
        "title": "Synology NAS",
        "color": "green",
        "fields": [
            {"key": "NAME_NAS", "label": "Display Name", "type": "text", "default": "Synology NAS"},
            {"key": "NAS_HOST", "label": "Host", "type": "text"},
            {"key": "NAS_SSH_USER", "label": "SSH Username", "type": "text"},
            {"key": "NAS_SSH_PASS", "label": "SSH Password", "type": "password"},
        ],
        "tests": ["ssh"],
    },
    "bike": {
        "title": "Bike Computer",
        "color": "pink",
        "fields": [
            {"key": "NAME_BIKE", "label": "Display Name", "type": "text", "default": "Bike Computer"},
            {"key": "BIKE_HOST", "label": "Host", "type": "text"},
            {"key": "BIKE_SSH_USER", "label": "SSH Username", "type": "text"},
            {"key": "BIKE_SSH_PASS", "label": "SSH Password", "type": "password"},
        ],
        "tests": ["ssh"],
    },
    "media": {
        "title": "Media Center VM",
        "color": "purple",
        "fields": [
            {"key": "NAME_MEDIA_CENTER", "label": "Display Name", "type": "text", "default": "Media Center"},
            {"key": "MEDIA_HOST", "label": "Host", "type": "text"},
            {"key": "MEDIA_SSH_USER", "label": "SSH Username", "type": "text"},
            {"key": "MEDIA_SSH_PASS", "label": "SSH Password", "type": "password"},
        ],
        "tests": ["ssh"],
    },
    "plex": {
        "title": "Plex Media Server",
        "color": "amber",
        "fields": [
            {"key": "PLEX_ENABLED", "label": "Show Plex Page", "type": "checkbox", "default": "false"},
            {"key": "NAME_PLEX", "label": "Display Name", "type": "text", "default": "Plex"},
            {"key": "PLEX_HOST", "label": "Host", "type": "text"},
            {"key": "PLEX_PORT", "label": "Port", "type": "number", "default": "32400"},
            {"key": "PLEX_TOKEN", "label": "X-Plex-Token", "type": "password"},
        ],
        "tests": ["api"],
        "auto_detect": True,
    },
    "overseerr": {
        "title": "Overseerr",
        "color": "purple",
        "fields": [
            {"key": "OVERSEERR_ENABLED", "label": "Show Overseerr Page", "type": "checkbox", "default": "false"},
            {"key": "NAME_OVERSEERR", "label": "Display Name", "type": "text", "default": "Overseerr"},
            {"key": "OVERSEERR_HOST", "label": "Host", "type": "text", "default": ""},
            {"key": "OVERSEERR_PORT", "label": "Port", "type": "number", "default": "5055"},
            {"key": "OVERSEERR_API_KEY", "label": "API Key", "type": "password"},
        ],
        "tests": ["api"],
        "auto_detect": True,
    },
    "media_services": {
        "title": "Media Services",
        "color": "amber",
        "fields": [
            {"key": "SHOW_DOWNLOADS", "label": "Show Downloads Page", "type": "checkbox", "default": "false"},
            {"key": "NAME_DOWNLOADS", "label": "Display Name", "type": "text", "default": "Downloads"},
            {"key": "SABNZBD_PORT", "label": "SABnzbd Port", "type": "number", "default": "8080"},
            {"key": "SABNZBD_API_KEY", "label": "SABnzbd API Key", "type": "password"},
            {"key": "SONARR_PORT", "label": "Sonarr Port", "type": "number", "default": "8989"},
            {"key": "SONARR_API_KEY", "label": "Sonarr API Key", "type": "password"},
            {"key": "RADARR_PORT", "label": "Radarr Port", "type": "number", "default": "7878"},
            {"key": "RADARR_API_KEY", "label": "Radarr API Key", "type": "password"},
            {"key": "PROWLARR_PORT", "label": "Prowlarr Port", "type": "number", "default": "9696"},
            {"key": "PROWLARR_API_KEY", "label": "Prowlarr API Key", "type": "password"},
        ],
        "tests": ["sabnzbd", "sonarr", "radarr", "prowlarr"],
        "auto_detect": True,
    },
}


def _escape_env_value(value):
    """Wrap .env value in double quotes if it contains special characters."""
    if any(c in value for c in (' ', '#', '"', "'", '\n', '\r', '\\', '$', '`')):
        escaped = value.replace('\\', '\\\\').replace('"', '\\"').replace('\n', '\\n')
        return f'"{escaped}"'
    return value


def update_env_key(key, value):
    """Update or add a key in the .env file and in os.environ. Thread-safe.

    Uses atomic write (write to temp file, then os.replace) to prevent
    data loss if the process crashes mid-write.
    """
    with _env_lock:
        os.environ[key] = value
        safe_value = _escape_env_value(value)
        lines = ENV_PATH.read_text().splitlines(keepends=True)
        found = False
        for i, line in enumerate(lines):
            if line.startswith(f"{key}="):
                lines[i] = f"{key}={safe_value}\n"
                found = True
                break
        if not found:
            lines.append(f"{key}={safe_value}\n")
        # Atomic write: write to a temp file first, then os.replace() swaps it in.
        # If the process crashes during write_text(), the original .env is untouched.
        # os.replace() is atomic on the same filesystem (POSIX guarantee, best-effort on Windows).
        tmp = ENV_PATH.with_suffix(".tmp")
        tmp.write_text("".join(lines))
        os.replace(str(tmp), str(ENV_PATH))


def get_all_settings():
    """Read all settings from os.environ, grouped by section."""
    result = {}
    with _env_lock:
        for section_id, section in SETTINGS_SCHEMA.items():
            fields = []
            for field in section["fields"]:
                fields.append({
                    **field,
                    "value": os.environ.get(field["key"], field.get("default", "")),
                })
            result[section_id] = {
                "title": section["title"],
                "color": section["color"],
                "fields": fields,
                "tests": section.get("tests", []),
                "auto_detect": section.get("auto_detect", False),
            }
    return result


def save_section(section_id, data):
    """Save settings for a section. Returns {success, restart_required}."""
    schema = SETTINGS_SCHEMA.get(section_id)
    if not schema:
        return {"success": False, "error": "Unknown section"}

    # Build a whitelist of accepted keys from the schema so clients can't
    # inject arbitrary env vars -- only keys defined in SETTINGS_SCHEMA pass through.
    valid_keys = {f["key"] for f in schema["fields"]}
    restart_required = False

    for key, value in data.items():
        if key not in valid_keys:
            continue
        value = str(value).strip()
        # Check if restart is needed
        field = next((f for f in schema["fields"] if f["key"] == key), None)
        if field and field.get("restart") and value != os.environ.get(key, ""):
            restart_required = True
        update_env_key(key, value)

        # Kill chat session when disabling Claude Chat
        if key == "CLAUDE_CHAT_ENABLED" and value.lower() != "true":
            try:
                from blueprints.chat_bp import kill_chat_session
                kill_chat_session()
            except Exception as e:
                import logging
                logging.getLogger(__name__).debug("Failed to kill chat session: %s", e)

    # Regenerate CLAUDE.md from template after saving
    try:
        from .claude_md_generator import generate_claude_md
        generate_claude_md()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("CLAUDE.md regen failed: %s", e)

    return {"success": True, "restart_required": restart_required}


def test_connection(system):
    """Test connectivity to a system. Returns {success, message, latency_ms}."""
    start = time.time()
    try:
        if system == "udm_api":
            host = os.environ.get("UDM_HOST", "")
            api_key = os.environ.get("UDM_API_KEY", "")
            r = requests.get(
                f"https://{host}/proxy/network/api/s/default/stat/health",
                headers={"X-API-KEY": api_key},
                verify=False, timeout=5,
            )
            r.raise_for_status()
            ms = int((time.time() - start) * 1000)
            return {"success": True, "message": f"API OK ({ms}ms)", "latency_ms": ms}

        elif system == "udm_ssh":
            return _test_ssh_kb_interactive(
                os.environ.get("UDM_HOST", ""),
                os.environ.get("UDM_SSH_USER", "root"),
                os.environ.get("UDM_SSH_PASS", ""),
                start,
            )

        elif system == "proxmox_api":
            host = os.environ.get("PROXMOX_HOST", "")
            port = os.environ.get("PROXMOX_PORT", "8006")
            token = os.environ.get("PROXMOX_TOKEN", "")
            r = requests.get(
                f"https://{host}:{port}/api2/json/version",
                headers={"Authorization": f"PVEAPIToken={token}"},
                verify=False, timeout=5,
            )
            r.raise_for_status()
            ms = int((time.time() - start) * 1000)
            return {"success": True, "message": f"API OK ({ms}ms)", "latency_ms": ms}

        elif system == "proxmox_ssh":
            return _test_ssh_simple(
                os.environ.get("PROXMOX_HOST", ""),
                os.environ.get("PROXMOX_SSH_USER", "root"),
                os.environ.get("PROXMOX_SSH_PASS", ""),
                start,
            )

        elif system == "ha_api":
            host = os.environ.get("HA_HOST", "")
            port = os.environ.get("HA_PORT", "8123")
            token = os.environ.get("HA_TOKEN", "")
            r = requests.get(
                f"http://{host}:{port}/api/",
                headers={"Authorization": f"Bearer {token}"},
                timeout=5,
            )
            r.raise_for_status()
            ms = int((time.time() - start) * 1000)
            return {"success": True, "message": f"API OK ({ms}ms)", "latency_ms": ms}

        elif system == "nas_ssh":
            return _test_ssh_kb_interactive(
                os.environ.get("NAS_HOST", ""),
                os.environ.get("NAS_SSH_USER", ""),
                os.environ.get("NAS_SSH_PASS", ""),
                start,
            )

        elif system == "bike_ssh":
            return _test_ssh_simple(
                os.environ.get("BIKE_HOST", ""),
                os.environ.get("BIKE_SSH_USER", ""),
                os.environ.get("BIKE_SSH_PASS", ""),
                start,
            )

        elif system == "media_ssh":
            return _test_ssh_simple(
                os.environ.get("MEDIA_HOST", ""),
                os.environ.get("MEDIA_SSH_USER", ""),
                os.environ.get("MEDIA_SSH_PASS", ""),
                start,
            )

        elif system == "sabnzbd":
            host = os.environ.get("MEDIA_HOST", "")
            port = os.environ.get("SABNZBD_PORT", "8080")
            api_key = os.environ.get("SABNZBD_API_KEY", "")
            r = requests.get(
                f"http://{host}:{port}/api",
                params={"mode": "version", "output": "json", "apikey": api_key},
                timeout=5,
            )
            r.raise_for_status()
            ms = int((time.time() - start) * 1000)
            return {"success": True, "message": f"SABnzbd OK ({ms}ms)", "latency_ms": ms}

        elif system == "sonarr":
            host = os.environ.get("MEDIA_HOST", "")
            port = os.environ.get("SONARR_PORT", "8989")
            api_key = os.environ.get("SONARR_API_KEY", "")
            r = requests.get(
                f"http://{host}:{port}/api/v3/system/status",
                headers={"X-Api-Key": api_key},
                timeout=5,
            )
            r.raise_for_status()
            ms = int((time.time() - start) * 1000)
            return {"success": True, "message": f"Sonarr OK ({ms}ms)", "latency_ms": ms}

        elif system == "radarr":
            host = os.environ.get("MEDIA_HOST", "")
            port = os.environ.get("RADARR_PORT", "7878")
            api_key = os.environ.get("RADARR_API_KEY", "")
            r = requests.get(
                f"http://{host}:{port}/api/v3/system/status",
                headers={"X-Api-Key": api_key},
                timeout=5,
            )
            r.raise_for_status()
            ms = int((time.time() - start) * 1000)
            return {"success": True, "message": f"Radarr OK ({ms}ms)", "latency_ms": ms}

        elif system == "plex_api":
            host = os.environ.get("PLEX_HOST", "")
            port = os.environ.get("PLEX_PORT", "32400")
            token = os.environ.get("PLEX_TOKEN", "")
            r = requests.get(
                f"http://{host}:{port}/",
                headers={"X-Plex-Token": token, "Accept": "application/json"},
                timeout=5,
            )
            r.raise_for_status()
            mc = r.json().get("MediaContainer", {})
            name = mc.get("friendlyName", "Plex")
            ms = int((time.time() - start) * 1000)
            return {"success": True, "message": f"{name} OK ({ms}ms)", "latency_ms": ms}

        elif system == "overseerr_api":
            host = os.environ.get("OVERSEERR_HOST", "")
            port = os.environ.get("OVERSEERR_PORT", "5055")
            api_key = os.environ.get("OVERSEERR_API_KEY", "")
            r = requests.get(
                f"http://{host}:{port}/api/v1/status",
                headers={"X-Api-Key": api_key},
                timeout=5,
            )
            r.raise_for_status()
            data = r.json()
            version = data.get("version", "?")
            ms = int((time.time() - start) * 1000)
            return {"success": True, "message": f"Overseerr v{version} OK ({ms}ms)", "latency_ms": ms}

        elif system == "prowlarr":
            host = os.environ.get("MEDIA_HOST", "")
            port = os.environ.get("PROWLARR_PORT", "9696")
            api_key = os.environ.get("PROWLARR_API_KEY", "")
            r = requests.get(
                f"http://{host}:{port}/api/v1/system/status",
                headers={"X-Api-Key": api_key},
                timeout=5,
            )
            r.raise_for_status()
            ms = int((time.time() - start) * 1000)
            return {"success": True, "message": f"Prowlarr OK ({ms}ms)", "latency_ms": ms}

        else:
            return {"success": False, "message": f"Unknown system: {system}"}

    except Exception as e:
        ms = int((time.time() - start) * 1000)
        return {"success": False, "message": str(e), "latency_ms": ms}


def auto_detect_media_keys():
    """SSH to media center and retrieve API keys from config files."""
    from .downloads import get_or_retrieve_api_keys
    return get_or_retrieve_api_keys()


def auto_detect_plex_token():
    """SSH to NAS and retrieve Plex token from Preferences.xml."""
    from .plex import auto_detect_plex_token as _detect
    return _detect()


def auto_detect_overseerr_key():
    """SSH to NAS and retrieve Overseerr API key from settings.json."""
    from .overseerr import auto_detect_overseerr_key as _detect
    return _detect()


def _test_ssh_simple(host, username, password, start):
    """Test SSH with standard password auth."""
    from .ssh_utils import safe_close
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(host, port=22, username=username, password=password, timeout=5)
        ms = int((time.time() - start) * 1000)
        return {"success": True, "message": f"SSH OK ({ms}ms)", "latency_ms": ms}
    finally:
        safe_close(client)


def _test_ssh_kb_interactive(host, username, password, start):
    """Test SSH with keyboard-interactive auth fallback."""
    from .ssh_utils import safe_close
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def kb_handler(title, instructions, prompt_list):
        return [password] * len(prompt_list)

    try:
        client.connect(
            host, port=22, username=username, password=password,
            look_for_keys=False, allow_agent=False, timeout=5,
        )
        transport = client.get_transport()
        if transport and not transport.is_authenticated():
            transport.auth_interactive(username, kb_handler)
        ms = int((time.time() - start) * 1000)
        return {"success": True, "message": f"SSH OK ({ms}ms)", "latency_ms": ms}
    finally:
        safe_close(client)
