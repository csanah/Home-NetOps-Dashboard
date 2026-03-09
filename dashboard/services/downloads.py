import os
import re
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime, timedelta
from pathlib import Path

import paramiko
import requests


TIMEOUT = 5


def _media_host():
    return os.environ.get("MEDIA_HOST", "")


def _sabnzbd_port():
    return int(os.environ.get("SABNZBD_PORT", "8080"))


def _sonarr_port():
    return int(os.environ.get("SONARR_PORT", "8989"))


def _prowlarr_port():
    return int(os.environ.get("PROWLARR_PORT", "9696"))


def _radarr_port():
    return int(os.environ.get("RADARR_PORT", "7878"))

# Paths to try for SABnzbd config on Windows
_user = os.environ.get("MEDIA_SSH_USER", "")
SABNZBD_INI_PATHS = [
    rf"C:\Users\{_user}\AppData\Local\sabnzbd\sabnzbd.ini",
    r"C:\ProgramData\SABnzbd\sabnzbd.ini",
    rf"C:\Users\{_user}\sabnzbd.ini",
]

ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def _ssh_read_file(client, path):
    """Read a file on the media center via SSH."""
    stdin, stdout, stderr = client.exec_command(f'type "{path}"', timeout=10)
    return stdout.read().decode("utf-8", errors="replace")


def _ssh_connect():
    """Open SSH connection to media center."""
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    client.connect(
        _media_host(), port=22,
        username=os.environ.get("MEDIA_SSH_USER", ""),
        password=os.environ.get("MEDIA_SSH_PASS", ""),
        timeout=10,
    )
    return client


def _update_env_key(key, value):
    """Update or add a key in the .env file and in os.environ."""
    os.environ[key] = value
    lines = ENV_PATH.read_text().splitlines(keepends=True)
    found = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}="):
            lines[i] = f"{key}={value}\n"
            found = True
            break
    if not found:
        lines.append(f"{key}={value}\n")
    ENV_PATH.write_text("".join(lines))


def get_or_retrieve_api_keys():
    """Return dict of api keys. If any are missing, SSH to retrieve them."""
    keys = {
        "sabnzbd": os.environ.get("SABNZBD_API_KEY", ""),
        "sonarr": os.environ.get("SONARR_API_KEY", ""),
        "radarr": os.environ.get("RADARR_API_KEY", ""),
        "prowlarr": os.environ.get("PROWLARR_API_KEY", ""),
    }
    missing = [k for k, v in keys.items() if not v]
    if not missing:
        return {"success": True, "keys": keys}

    try:
        client = _ssh_connect()
    except Exception as e:
        return {"success": False, "error": f"SSH failed: {e}", "keys": keys}

    errors = []

    # SABnzbd — parse ini for api_key
    if not keys["sabnzbd"]:
        found = False
        for path in SABNZBD_INI_PATHS:
            content = _ssh_read_file(client, path)
            if content and "api_key" in content:
                match = re.search(r'^api_key\s*=\s*(.+)$', content, re.MULTILINE)
                if match:
                    keys["sabnzbd"] = match.group(1).strip()
                    _update_env_key("SABNZBD_API_KEY", keys["sabnzbd"])
                    found = True
                    break
        if not found:
            errors.append("SABnzbd: could not find api_key in config")

    # Sonarr — parse config.xml
    if not keys["sonarr"]:
        content = _ssh_read_file(client, r"C:\ProgramData\Sonarr\config.xml")
        if content:
            try:
                root = ET.fromstring(content)
                api_key = root.findtext("ApiKey")
                if api_key:
                    keys["sonarr"] = api_key
                    _update_env_key("SONARR_API_KEY", keys["sonarr"])
            except ET.ParseError:
                errors.append("Sonarr: failed to parse config.xml")
        else:
            errors.append("Sonarr: config.xml not found")

    # Radarr — parse config.xml
    if not keys["radarr"]:
        content = _ssh_read_file(client, r"C:\ProgramData\Radarr\config.xml")
        if content:
            try:
                root = ET.fromstring(content)
                api_key = root.findtext("ApiKey")
                if api_key:
                    keys["radarr"] = api_key
                    _update_env_key("RADARR_API_KEY", keys["radarr"])
            except ET.ParseError:
                errors.append("Radarr: failed to parse config.xml")
        else:
            errors.append("Radarr: config.xml not found")

    # Prowlarr — parse config.xml
    if not keys["prowlarr"]:
        content = _ssh_read_file(client, r"C:\ProgramData\Prowlarr\config.xml")
        if content:
            try:
                root = ET.fromstring(content)
                api_key = root.findtext("ApiKey")
                if api_key:
                    keys["prowlarr"] = api_key
                    _update_env_key("PROWLARR_API_KEY", keys["prowlarr"])
            except ET.ParseError:
                errors.append("Prowlarr: failed to parse config.xml")
        else:
            errors.append("Prowlarr: config.xml not found")

    client.close()
    return {
        "success": len(errors) == 0,
        "errors": errors,
        "keys": keys,
    }


# ── API Fetchers ──

def _fetch_sabnzbd_queue():
    api_key = os.environ.get("SABNZBD_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    r = requests.get(
        f"http://{_media_host()}:{_sabnzbd_port()}/api",
        params={"mode": "queue", "output": "json", "apikey": api_key},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json().get("queue", {})
    return {
        "speed": data.get("speed", "0 B/s"),
        "size_left": data.get("sizeleft", "0 B"),
        "time_left": data.get("timeleft", "0:00:00"),
        "paused": data.get("paused", False),
        "slots": [
            {
                "filename": s.get("filename", "?"),
                "size": s.get("size", "?"),
                "size_left": s.get("sizeleft", "?"),
                "percentage": s.get("percentage", "0"),
                "eta": s.get("timeleft", "?"),
                "status": s.get("status", "?"),
            }
            for s in data.get("slots", [])
        ],
    }


def _fetch_sabnzbd_history(limit=20):
    api_key = os.environ.get("SABNZBD_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    r = requests.get(
        f"http://{_media_host()}:{_sabnzbd_port()}/api",
        params={"mode": "history", "limit": limit, "output": "json", "apikey": api_key},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json().get("history", {})
    return {
        "total_size": data.get("total_size", "0 B"),
        "slots": [
            {
                "name": s.get("name", "?"),
                "size": s.get("size", "?"),
                "status": s.get("status", "?"),
                "completed": s.get("completed", 0),
                "category": s.get("category", ""),
            }
            for s in data.get("slots", [])
        ],
    }


def _fetch_sonarr_queue():
    api_key = os.environ.get("SONARR_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    r = requests.get(
        f"http://{_media_host()}:{_sonarr_port()}/api/v3/queue",
        headers={"X-Api-Key": api_key},
        params={"pageSize": 20, "includeEpisode": "true", "includeSeries": "true"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    records = data.get("records", [])
    return {
        "total": data.get("totalRecords", 0),
        "items": [
            {
                "series": rec.get("series", {}).get("title", "?"),
                "episode_title": rec.get("episode", {}).get("title", "?"),
                "season": rec.get("episode", {}).get("seasonNumber", 0),
                "episode": rec.get("episode", {}).get("episodeNumber", 0),
                "quality": rec.get("quality", {}).get("quality", {}).get("name", "?"),
                "size": rec.get("size", 0),
                "size_left": rec.get("sizeleft", 0),
                "status": rec.get("status", "?"),
                "tracked_status": rec.get("trackedDownloadStatus", ""),
                "tracked_state": rec.get("trackedDownloadState", ""),
            }
            for rec in records
        ],
    }


def _fetch_sonarr_calendar(days=14):
    api_key = os.environ.get("SONARR_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    start = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    r = requests.get(
        f"http://{_media_host()}:{_sonarr_port()}/api/v3/calendar",
        headers={"X-Api-Key": api_key},
        params={"start": start, "end": end, "includeSeries": "true"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    episodes = r.json()
    return {
        "episodes": [
            {
                "series": ep.get("series", {}).get("title", "?"),
                "title": ep.get("title", "?"),
                "season": ep.get("seasonNumber", 0),
                "episode": ep.get("episodeNumber", 0),
                "air_date": ep.get("airDateUtc", ""),
                "monitored": ep.get("monitored", False),
                "has_file": ep.get("hasFile", False),
            }
            for ep in episodes
        ],
    }


def _fetch_radarr_queue():
    api_key = os.environ.get("RADARR_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    r = requests.get(
        f"http://{_media_host()}:{_radarr_port()}/api/v3/queue",
        headers={"X-Api-Key": api_key},
        params={"pageSize": 20, "includeMovie": "true"},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    data = r.json()
    records = data.get("records", [])
    return {
        "total": data.get("totalRecords", 0),
        "items": [
            {
                "title": rec.get("movie", {}).get("title", "?"),
                "year": rec.get("movie", {}).get("year", 0),
                "quality": rec.get("quality", {}).get("quality", {}).get("name", "?"),
                "size": rec.get("size", 0),
                "size_left": rec.get("sizeleft", 0),
                "status": rec.get("status", "?"),
                "tracked_status": rec.get("trackedDownloadStatus", ""),
                "tracked_state": rec.get("trackedDownloadState", ""),
            }
            for rec in records
        ],
    }


def _fetch_radarr_calendar(days=14):
    api_key = os.environ.get("RADARR_API_KEY", "")
    if not api_key:
        return {"error": "no_key"}
    start = datetime.now().strftime("%Y-%m-%d")
    end = (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")
    r = requests.get(
        f"http://{_media_host()}:{_radarr_port()}/api/v3/calendar",
        headers={"X-Api-Key": api_key},
        params={"start": start, "end": end},
        timeout=TIMEOUT,
    )
    r.raise_for_status()
    movies = r.json()
    return {
        "movies": [
            {
                "title": m.get("title", "?"),
                "year": m.get("year", 0),
                "release_date": m.get("digitalRelease") or m.get("physicalRelease") or m.get("inCinemas", ""),
                "monitored": m.get("monitored", False),
                "has_file": m.get("hasFile", False),
                "status": m.get("status", ""),
            }
            for m in movies
        ],
    }


def get_downloads_data():
    """Fetch all download data in parallel. Each source independent."""
    results = {
        "sabnzbd_queue": None,
        "sabnzbd_history": None,
        "sonarr_queue": None,
        "sonarr_calendar": None,
        "radarr_queue": None,
        "radarr_calendar": None,
    }

    fetchers = {
        "sabnzbd_queue": _fetch_sabnzbd_queue,
        "sabnzbd_history": _fetch_sabnzbd_history,
        "sonarr_queue": _fetch_sonarr_queue,
        "sonarr_calendar": _fetch_sonarr_calendar,
        "radarr_queue": _fetch_radarr_queue,
        "radarr_calendar": _fetch_radarr_calendar,
    }

    with ThreadPoolExecutor(max_workers=6) as pool:
        futures = {pool.submit(fn): key for key, fn in fetchers.items()}
        try:
            for future in as_completed(futures, timeout=10):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    results[key] = {"error": str(e)}
        except TimeoutError:
            # Mark any futures that didn't complete as timed out
            for future, key in futures.items():
                if results[key] is None:
                    results[key] = {"error": "Request timed out"}

    # Check if keys are configured
    results["has_sabnzbd_key"] = bool(os.environ.get("SABNZBD_API_KEY", ""))
    results["has_sonarr_key"] = bool(os.environ.get("SONARR_API_KEY", ""))
    results["has_prowlarr_key"] = bool(os.environ.get("PROWLARR_API_KEY", ""))
    results["has_radarr_key"] = bool(os.environ.get("RADARR_API_KEY", ""))

    return results
