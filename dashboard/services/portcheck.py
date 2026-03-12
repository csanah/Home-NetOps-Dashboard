from __future__ import annotations

import os
import socket


def tcp_check(host: str, port: int, timeout: int = 5) -> bool:
    try:
        s = socket.create_connection((host, port), timeout=timeout)
        s.close()
        return True
    except Exception:
        return False


def get_bike_health() -> dict[str, object]:
    host = os.environ.get("BIKE_HOST", "")
    return {
        "name": "Bike Computer",
        "host": host,
        "online": tcp_check(host, 22) if host else False,
    }


def get_nas_health() -> dict[str, object]:
    host = os.environ.get("NAS_HOST", "")
    return {
        "name": "Synology NAS",
        "host": host,
        "online": tcp_check(host, 22) if host else False,
    }


def get_mqtt_health() -> dict[str, object]:
    host = os.environ.get("HA_HOST", "")
    return {
        "name": "MQTT Broker",
        "host": f"{host}:1883",
        "online": tcp_check(host, 1883),
    }
