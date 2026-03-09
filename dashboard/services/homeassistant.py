import os
from .http_client import create_session

_session = create_session()


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
        r = _session.get(f"{base}/", headers=headers, timeout=8)
        r.raise_for_status()
    except Exception:
        return info

    info["online"] = True

    # Config
    try:
        r = _session.get(f"{base}/config", headers=headers, timeout=8)
        r.raise_for_status()
        info["version"] = r.json().get("version", "?")
    except Exception:
        pass

    # States
    try:
        r = _session.get(f"{base}/states", headers=headers, timeout=8)
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
    except Exception:
        pass

    return info
