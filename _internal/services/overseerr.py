import os
import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from pathlib import Path

import paramiko

from .http_client import get_shared_session
from .config import TIMEOUTS

_session = get_shared_session()


TIMEOUT = TIMEOUTS["overseerr"]
from runtime import ENV_PATH


def _overseerr_host():
    return os.environ.get("OVERSEERR_HOST", "")


def _overseerr_port():
    return int(os.environ.get("OVERSEERR_PORT", "5055"))


def _overseerr_api_key():
    return os.environ.get("OVERSEERR_API_KEY", "")


def _base_url():
    return f"http://{_overseerr_host()}:{_overseerr_port()}"


def _headers():
    return {
        "X-Api-Key": _overseerr_api_key(),
        "Accept": "application/json",
    }


def _time_ago(date_str):
    """Convert ISO date string to human-readable time ago."""
    if not date_str:
        return ""
    try:
        from datetime import datetime, timezone
        # Handle ISO format like "2026-03-08T12:34:56.000Z"
        dt_str = date_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(dt_str)
        now = datetime.now(timezone.utc)
        diff = (now - dt).total_seconds()
        if diff < 60:
            return "just now"
        elif diff < 3600:
            m = int(diff // 60)
            return f"{m} minute{'s' if m != 1 else ''} ago"
        elif diff < 86400:
            h = int(diff // 3600)
            return f"{h} hour{'s' if h != 1 else ''} ago"
        elif diff < 604800:
            d = int(diff // 86400)
            return f"{d} day{'s' if d != 1 else ''} ago"
        else:
            w = int(diff // 604800)
            return f"{w} week{'s' if w != 1 else ''} ago"
    except (ValueError, TypeError):
        return str(date_str)[:10] if date_str else ""


def _status_label(status):
    """Map Overseerr media status codes to labels."""
    mapping = {
        1: "unknown",
        2: "pending",
        3: "processing",
        4: "partially_available",
        5: "available",
    }
    return mapping.get(status, "unknown")


def _request_status_label(status):
    """Map Overseerr request status codes to labels."""
    mapping = {
        1: "pending",
        2: "approved",
        3: "declined",
    }
    return mapping.get(status, "unknown")


# ── Title Resolution ──

def _resolve_title(media_type, tmdb_id):
    """Fetch title for a single media item from Overseerr's TMDB proxy."""
    try:
        endpoint = "movie" if media_type == "movie" else "tv"
        r = _session.get(
            f"{_base_url()}/api/v1/{endpoint}/{tmdb_id}",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return data.get("title") or data.get("name") or "Unknown"
    except Exception:
        return "Unknown"


def _resolve_titles(results_list):
    """Resolve titles for all requests in parallel. Returns {tmdb_id: title}."""
    pairs = {}
    for req in results_list:
        media = req.get("media", {})
        tmdb_id = media.get("tmdbId")
        media_type = req.get("type", media.get("mediaType", "movie"))
        if tmdb_id and tmdb_id not in pairs:
            pairs[tmdb_id] = media_type

    title_map = {}
    if not pairs:
        return title_map

    with ThreadPoolExecutor(max_workers=min(len(pairs), 8)) as pool:
        futures = {
            pool.submit(_resolve_title, mt, tid): tid
            for tid, mt in pairs.items()
        }
        for future in as_completed(futures, timeout=10):
            tid = futures[future]
            try:
                title_map[tid] = future.result()
            except Exception:
                title_map[tid] = "Unknown"

    return title_map


# ── API Fetchers ──

def _fetch_request_stats():
    """Fetch request counts by status."""
    try:
        r = _session.get(
            f"{_base_url()}/api/v1/request/count",
            headers=_headers(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        return {
            "total": data.get("total", 0),
            "pending": data.get("pending", 0),
            "approved": data.get("approved", 0),
            "available": data.get("available", 0),
            "processing": data.get("processing", 0),
            "declined": data.get("declined", 0),
        }
    except Exception as e:
        return {"error": str(e)}


def _fetch_pending_requests():
    """Fetch requests awaiting approval."""
    try:
        r = _session.get(
            f"{_base_url()}/api/v1/request",
            headers=_headers(),
            params={"filter": "pending", "take": 10, "sort": "added"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        results_list = data.get("results", [])
        title_map = _resolve_titles(results_list)

        items = []
        for req in results_list:
            media = req.get("media", {})
            tmdb_id = media.get("tmdbId")
            media_type = req.get("type", media.get("mediaType", "unknown"))
            requester = req.get("requestedBy", {})
            title = title_map.get(tmdb_id, "Unknown")

            items.append({
                "title": title,
                "media_type": media_type,
                "requester": requester.get("displayName", requester.get("email", "Unknown")),
                "requested_at": _time_ago(req.get("createdAt", "")),
                "status": _request_status_label(req.get("status", 1)),
            })
        return {"items": items}
    except Exception as e:
        return {"error": str(e)}


def _fetch_recent_requests():
    """Fetch last 10 requests regardless of status."""
    try:
        r = _session.get(
            f"{_base_url()}/api/v1/request",
            headers=_headers(),
            params={"take": 10, "sort": "added"},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        results_list = data.get("results", [])
        title_map = _resolve_titles(results_list)

        items = []
        for req in results_list:
            media = req.get("media", {})
            tmdb_id = media.get("tmdbId")
            media_type = req.get("type", media.get("mediaType", "unknown"))
            requester = req.get("requestedBy", {})
            title = title_map.get(tmdb_id, "Unknown")

            req_status = _request_status_label(req.get("status", 1))
            media_status = _status_label(media.get("status", 1))
            display_status = "available" if media_status == "available" else req_status

            items.append({
                "title": title,
                "media_type": media_type,
                "requester": requester.get("displayName", requester.get("email", "Unknown")),
                "requested_at": _time_ago(req.get("createdAt", "")),
                "status": display_status,
            })
        return {"items": items}
    except Exception as e:
        return {"error": str(e)}


def _fetch_trending():
    """Fetch trending movies and TV from TMDB via Overseerr."""
    try:
        items = []
        # Fetch trending combined (movies + TV)
        r = _session.get(
            f"{_base_url()}/api/v1/discover/trending",
            headers=_headers(),
            params={"page": 1},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        data = r.json()
        for item in data.get("results", [])[:12]:
            media_type = item.get("mediaType", "unknown")
            title = item.get("title") or item.get("name") or "Unknown"
            year = ""
            date_str = item.get("releaseDate") or item.get("firstAirDate") or ""
            if date_str:
                year = date_str[:4]

            # Check if already requested/available
            media_info = item.get("mediaInfo")
            status = None
            if media_info:
                status = _status_label(media_info.get("status", 1))

            items.append({
                "title": title,
                "media_type": media_type,
                "year": year,
                "status": status,
            })
        return {"items": items}
    except Exception as e:
        return {"error": str(e)}


def get_overseerr_data():
    """Fetch all Overseerr data in parallel."""
    if not _overseerr_host() or not _overseerr_api_key():
        return {
            "stats": None, "pending": None,
            "recent": None, "trending": None,
            "has_key": bool(_overseerr_api_key()),
        }

    results = {
        "stats": None,
        "pending": None,
        "recent": None,
        "trending": None,
    }

    fetchers = {
        "stats": _fetch_request_stats,
        "pending": _fetch_pending_requests,
        "recent": _fetch_recent_requests,
        "trending": _fetch_trending,
    }

    with ThreadPoolExecutor(max_workers=4) as pool:
        futures = {pool.submit(fn): key for key, fn in fetchers.items()}
        try:
            for future in as_completed(futures, timeout=10):
                key = futures[future]
                try:
                    results[key] = future.result()
                except Exception as e:
                    results[key] = {"error": str(e)}
        except TimeoutError:
            for future, key in futures.items():
                if results[key] is None:
                    results[key] = {"error": "Request timed out"}

    results["has_key"] = bool(_overseerr_api_key())
    return results


def auto_detect_overseerr_key():
    """SSH to NAS and find Overseerr API key from settings.json."""
    nas_host = os.environ.get("NAS_HOST", "")
    nas_user = os.environ.get("NAS_SSH_USER", "")
    nas_pass = os.environ.get("NAS_SSH_PASS", "")

    if not nas_host or not nas_user or not nas_pass:
        return {"success": False, "error": "NAS SSH credentials not configured"}

    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    def kb_handler(title, instructions, prompt_list):
        return [nas_pass] * len(prompt_list)

    try:
        client.connect(
            nas_host, port=22, username=nas_user, password=nas_pass,
            look_for_keys=False, allow_agent=False, timeout=10,
        )
        transport = client.get_transport()
        if transport and not transport.is_authenticated():
            transport.auth_interactive(nas_user, kb_handler)
    except Exception as e:
        return {"success": False, "error": f"SSH connection failed: {e}"}

    # Common Overseerr config paths on Synology Docker
    search_paths = [
        "/volume1/docker/overseerr/config/settings.json",
        "/volume1/docker/overseerr/app/config/settings.json",
        "/volume2/docker/overseerr/config/settings.json",
    ]

    api_key = None
    found_path = None

    for path in search_paths:
        try:
            stdin, stdout, stderr = client.exec_command(f'cat "{path}"', timeout=10)
            content = stdout.read().decode("utf-8", errors="replace")
            if content:
                data = json.loads(content)
                key = data.get("main", {}).get("apiKey") or data.get("apiKey")
                if key:
                    api_key = key
                    found_path = path
                    break
        except Exception:
            continue

    # If not found in known paths, try find command
    if not api_key:
        try:
            stdin, stdout, stderr = client.exec_command(
                'find /volume1 /volume2 -name "settings.json" -path "*/overseerr/*" 2>/dev/null | head -5',
                timeout=15,
            )
            paths = stdout.read().decode("utf-8", errors="replace").strip().split("\n")
            for path in paths:
                path = path.strip()
                if not path:
                    continue
                stdin, stdout, stderr = client.exec_command(f'cat "{path}"', timeout=10)
                content = stdout.read().decode("utf-8", errors="replace")
                if content:
                    try:
                        data = json.loads(content)
                        key = data.get("main", {}).get("apiKey") or data.get("apiKey")
                        if key:
                            api_key = key
                            found_path = path
                            break
                    except json.JSONDecodeError:
                        continue
        except Exception:
            pass

    client.close()

    if not api_key:
        return {"success": False, "error": "Could not find Overseerr API key in settings.json"}

    # Save key to .env
    from .settings import update_env_key
    update_env_key("OVERSEERR_API_KEY", api_key)
    if not os.environ.get("OVERSEERR_HOST"):
        update_env_key("OVERSEERR_HOST", nas_host)

    return {
        "success": True,
        "message": f"API key found in {found_path}",
        "key": api_key[:8] + "..." if len(api_key) > 8 else "***",
    }
