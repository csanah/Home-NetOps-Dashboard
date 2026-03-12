import logging
import os
from .http_client import get_shared_session
from .config import TIMEOUTS

logger = logging.getLogger(__name__)

_session = get_shared_session()


def get_health():
    host = os.environ.get("HA_HOST", "")
    port = os.environ.get("HA_PORT", "8123")
    token = os.environ.get("HA_TOKEN", "")
    headers = {"Authorization": f"Bearer {token}"}
    base = f"http://{host}:{port}/api"

    info = {
        "name": "Home Assistant",
        "host": f"{host}:{port}",
        "online": False,
        "version": "?",
        "entity_count": 0,
        "bike_entities": 0,
        "unavailable_bike": 0,
    }

    # Check API
    try:
        r = _session.get(f"{base}/", headers=headers, timeout=(3, 8))
        r.raise_for_status()
    except Exception:
        return info

    info["online"] = True

    # Config
    try:
        r = _session.get(f"{base}/config", headers=headers, timeout=(3, 8))
        r.raise_for_status()
        info["version"] = r.json().get("version", "?")
    except Exception as e:
        logger.debug("Failed to fetch HA config: %s", e)

    # States
    try:
        r = _session.get(f"{base}/states", headers=headers, timeout=TIMEOUTS["http_slow"])
        r.raise_for_status()
        states = r.json()
        info["entity_count"] = len(states)
        bike = [
            s for s in states
            if "bike" in s.get("entity_id", "").lower()
            or "bike" in s.get("attributes", {}).get("friendly_name", "").lower()
        ]
        info["bike_entities"] = len(bike)
        info["unavailable_bike"] = len([s for s in bike if s.get("state") == "unavailable"])
    except Exception as e:
        logger.debug("Failed to fetch HA states: %s", e)

    return info
