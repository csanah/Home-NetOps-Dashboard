import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed, TimeoutError
from datetime import datetime
from pathlib import Path

import paramiko
import requests


TIMEOUT = 5
ENV_PATH = Path(__file__).resolve().parent.parent.parent / ".env"


def _plex_host():
    return os.environ.get("PLEX_HOST", "")


def _plex_port():
    return int(os.environ.get("PLEX_PORT", "32400"))


def _plex_token():
    return os.environ.get("PLEX_TOKEN", "")


def _plex_headers():
    return {
        "X-Plex-Token": _plex_token(),
        "Accept": "application/json",
    }


def _base_url():
    return f"http://{_plex_host()}:{_plex_port()}"


def _format_duration(ms):
    """Convert milliseconds to human-readable duration like '1h 23m'."""
    if not ms:
        return "0m"
    total_seconds = int(ms) // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    if hours > 0:
        return f"{hours}h {minutes}m"
    return f"{minutes}m"


def _time_ago(unix_ts):
    """Convert unix timestamp to human-readable time ago string."""
    if not unix_ts:
        return ""
    try:
        diff = time.time() - int(unix_ts)
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
        return ""


# ── API Fetchers ──

def _fetch_server_info():
    try:
        r = requests.get(
            f"{_base_url()}/",
            headers=_plex_headers(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        mc = r.json().get("MediaContainer", {})
        return {
            "name": mc.get("friendlyName", "Plex"),
            "version": mc.get("version", "?"),
            "platform": mc.get("platform", "?"),
            "online": True,
        }
    except Exception as e:
        return {"error": str(e)}


def _fetch_library_counts(key):
    """Fetch total and unwatched counts for a library section."""
    params = {"X-Plex-Container-Size": 0, "X-Plex-Container-Start": 0}
    total = 0
    unwatched = 0
    # Total count
    r = requests.get(
        f"{_base_url()}/library/sections/{key}/all",
        headers=_plex_headers(), params=params, timeout=TIMEOUT,
    )
    r.raise_for_status()
    total = r.json().get("MediaContainer", {}).get("totalSize", 0)
    # Unwatched count
    try:
        r2 = requests.get(
            f"{_base_url()}/library/sections/{key}/unwatched",
            headers=_plex_headers(), params=params, timeout=TIMEOUT,
        )
        r2.raise_for_status()
        unwatched = r2.json().get("MediaContainer", {}).get("totalSize", 0)
    except Exception:
        pass
    return {"total": total, "unwatched": unwatched}


def _fetch_libraries():
    try:
        r = requests.get(
            f"{_base_url()}/library/sections",
            headers=_plex_headers(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        mc = r.json().get("MediaContainer", {})
        sections = []
        for d in mc.get("Directory", []):
            sections.append({
                "title": d.get("title", "?"),
                "type": d.get("type", "?"),
                "count": 0,
                "unwatched": 0,
                "key": d.get("key", ""),
            })

        # Fetch total + unwatched counts in parallel
        total_items = 0
        total_unwatched = 0
        with ThreadPoolExecutor(max_workers=len(sections) or 1) as pool:
            future_to_idx = {
                pool.submit(_fetch_library_counts, s["key"]): i
                for i, s in enumerate(sections) if s["key"]
            }
            for future in as_completed(future_to_idx, timeout=10):
                idx = future_to_idx[future]
                try:
                    counts = future.result()
                    sections[idx]["count"] = counts["total"]
                    sections[idx]["unwatched"] = counts["unwatched"]
                    total_items += counts["total"]
                    total_unwatched += counts["unwatched"]
                except Exception:
                    pass

        return {"sections": sections, "total_items": total_items, "total_unwatched": total_unwatched}
    except Exception as e:
        return {"error": str(e)}


def _fetch_sessions():
    try:
        r = requests.get(
            f"{_base_url()}/status/sessions",
            headers=_plex_headers(),
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        mc = r.json().get("MediaContainer", {})
        sessions = []
        for m in mc.get("Metadata", []):
            duration = int(m.get("duration", 0))
            view_offset = int(m.get("viewOffset", 0))
            progress = round((view_offset / duration) * 100) if duration else 0

            # Get user info
            user = m.get("User", {})
            username = user.get("title", "Unknown")

            # Get player info
            player = m.get("Player", {})
            device = player.get("device", player.get("product", "?"))
            state = player.get("state", "playing")

            # Get quality/transcode info
            media = m.get("Media", [{}])[0] if m.get("Media") else {}
            quality = media.get("videoResolution", "?")
            if quality and quality != "?":
                quality = quality + "p" if quality.isdigit() else quality

            # Title handling for TV shows
            title = m.get("title", "?")
            grandparent = m.get("grandparentTitle", "")
            parent_index = m.get("parentIndex")
            index = m.get("index")
            subtitle = ""
            if grandparent:
                subtitle = grandparent
                if parent_index and index:
                    subtitle += f" — S{int(parent_index):02d}E{int(index):02d}"

            sessions.append({
                "title": title,
                "subtitle": subtitle,
                "user": username,
                "user_initial": username[0].upper() if username else "?",
                "progress": progress,
                "duration": _format_duration(duration),
                "remaining": _format_duration(duration - view_offset),
                "device": device,
                "state": state,
                "quality": quality,
            })
        return {"sessions": sessions, "count": mc.get("size", len(sessions))}
    except Exception as e:
        return {"error": str(e)}


def _fetch_recently_added():
    try:
        r = requests.get(
            f"{_base_url()}/library/recentlyAdded",
            headers=_plex_headers(),
            params={"X-Plex-Container-Size": 50},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        mc = r.json().get("MediaContainer", {})
        items = []
        for m in mc.get("Metadata", []):
            media_type = m.get("type", "?")
            if media_type == "season":
                continue  # Skip season folders, show actual media only
            title = m.get("title", "?")
            grandparent = m.get("grandparentTitle", "")
            parent_index = m.get("parentIndex")
            index = m.get("index")

            if grandparent:
                display_title = grandparent
                if parent_index and index:
                    display_title += f" — S{int(parent_index):02d}E{int(index):02d}"
                display_title += f" — {title}"
            else:
                display_title = title

            items.append({
                "title": display_title,
                "type": media_type,
                "year": m.get("year", ""),
                "added_at": _time_ago(m.get("addedAt")),
            })
            if len(items) >= 12:
                break
        return {"items": items}
    except Exception as e:
        return {"error": str(e)}


def _fetch_on_deck():
    try:
        r = requests.get(
            f"{_base_url()}/library/onDeck",
            headers=_plex_headers(),
            params={"X-Plex-Container-Size": 10},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        mc = r.json().get("MediaContainer", {})
        items = []
        for m in mc.get("Metadata", []):
            duration = int(m.get("duration", 0))
            view_offset = int(m.get("viewOffset", 0))
            progress = round((view_offset / duration) * 100) if duration else 0

            title = m.get("title", "?")
            grandparent = m.get("grandparentTitle", "")
            parent_index = m.get("parentIndex")
            index = m.get("index")

            if grandparent:
                display_title = grandparent
                if parent_index and index:
                    display_title += f" — S{int(parent_index):02d}E{int(index):02d}"
                display_title += f" — {title}"
            else:
                display_title = title

            items.append({
                "title": display_title,
                "progress": progress,
            })
        return {"items": items}
    except Exception as e:
        return {"error": str(e)}


def _fetch_history():
    """Fetch recent watch history."""
    try:
        r = requests.get(
            f"{_base_url()}/status/sessions/history/all",
            headers=_plex_headers(),
            params={
                "sort": "viewedAt:desc",
                "X-Plex-Container-Size": 15,
                "X-Plex-Container-Start": 0,
            },
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        mc = r.json().get("MediaContainer", {})
        # Account ID → name mapping (best-effort)
        account_map = {}
        items = []
        for m in mc.get("Metadata", []):
            title = m.get("title", "?")
            grandparent = m.get("grandparentTitle", "")
            parent_index = m.get("parentIndex")
            index = m.get("index")

            if grandparent:
                display_title = grandparent
                if parent_index and index:
                    display_title += f" — S{int(parent_index):02d}E{int(index):02d}"
                display_title += f" — {title}"
            else:
                display_title = title

            viewed_at = m.get("viewedAt")
            account_id = m.get("accountID")

            items.append({
                "title": display_title,
                "type": m.get("type", "?"),
                "viewed_at": _time_ago(viewed_at),
                "account_id": account_id,
            })
            if len(items) >= 12:
                break

        # Try to resolve account names from bandwidth stats (cached)
        try:
            bw = requests.get(
                f"{_base_url()}/statistics/bandwidth",
                headers=_plex_headers(),
                params={"timespan": 4},
                timeout=TIMEOUT,
            )
            if bw.ok:
                for acct in bw.json().get("MediaContainer", {}).get("Account", []):
                    account_map[acct.get("id")] = acct.get("name", f"User {acct.get('id')}")
        except Exception:
            pass

        for item in items:
            aid = item.get("account_id")
            item["account_name"] = account_map.get(aid, f"User {aid}" if aid else "?")

        return {"items": items}
    except Exception as e:
        return {"error": str(e)}


def _fetch_bandwidth_stats():
    """Fetch monthly bandwidth stats per account with LAN/WAN breakdown."""
    try:
        r = requests.get(
            f"{_base_url()}/statistics/bandwidth",
            headers=_plex_headers(),
            params={"timespan": 4},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        mc = r.json().get("MediaContainer", {})

        # Build account name map
        account_map = {}
        for acct in mc.get("Account", []):
            account_map[acct.get("id")] = acct.get("name", f"User {acct.get('id')}")

        # Aggregate bytes per account, split by lan/wan
        per_account = {}  # id -> {name, lan, wan}
        for entry in mc.get("StatisticsBandwidth", []):
            aid = entry.get("accountID")
            if aid not in per_account:
                per_account[aid] = {
                    "name": account_map.get(aid, f"User {aid}"),
                    "lan": 0,
                    "wan": 0,
                }
            bw_bytes = entry.get("bytes", 0)
            if entry.get("lan", False):
                per_account[aid]["lan"] += bw_bytes
            else:
                per_account[aid]["wan"] += bw_bytes

        accounts = []
        total_lan = 0
        total_wan = 0
        for aid, info in per_account.items():
            total = info["lan"] + info["wan"]
            total_lan += info["lan"]
            total_wan += info["wan"]
            accounts.append({
                "name": info["name"],
                "lan_gb": round(info["lan"] / (1024**3), 1),
                "wan_gb": round(info["wan"] / (1024**3), 1),
                "total_gb": round(total / (1024**3), 1),
            })
        # Sort by total descending
        accounts.sort(key=lambda a: a["total_gb"], reverse=True)

        grand_total = total_lan + total_wan
        lan_pct = round((total_lan / grand_total) * 100) if grand_total else 0

        return {
            "accounts": accounts,
            "total_lan_gb": round(total_lan / (1024**3), 1),
            "total_wan_gb": round(total_wan / (1024**3), 1),
            "lan_pct": lan_pct,
        }
    except Exception as e:
        return {"error": str(e)}


def search_plex(query):
    """Search Plex libraries."""
    if not _plex_host() or not _plex_token() or not query:
        return {"results": [], "query": query}
    try:
        r = requests.get(
            f"{_base_url()}/hubs/search",
            headers=_plex_headers(),
            params={"query": query, "limit": 10},
            timeout=TIMEOUT,
        )
        r.raise_for_status()
        mc = r.json().get("MediaContainer", {})
        results = []
        for hub in mc.get("Hub", []):
            hub_type = hub.get("type", "?")
            for m in hub.get("Metadata", []):
                title = m.get("title", "?")
                grandparent = m.get("grandparentTitle", "")
                year = m.get("year", "")
                media_type = m.get("type", hub_type)

                display_title = title
                if grandparent:
                    parent_index = m.get("parentIndex")
                    index = m.get("index")
                    display_title = grandparent
                    if parent_index and index:
                        display_title += f" — S{int(parent_index):02d}E{int(index):02d}"
                    display_title += f" — {title}"

                results.append({
                    "title": display_title,
                    "type": media_type,
                    "year": year,
                })
        return {"results": results, "query": query}
    except Exception as e:
        return {"results": [], "query": query, "error": str(e)}


def get_plex_data():
    """Fetch all Plex data in parallel."""
    if not _plex_host() or not _plex_token():
        return {
            "server": None, "libraries": None, "sessions": None,
            "recently_added": None, "on_deck": None,
            "history": None, "bandwidth": None,
            "has_token": bool(_plex_token()),
        }

    results = {
        "server": None,
        "libraries": None,
        "sessions": None,
        "recently_added": None,
        "on_deck": None,
        "history": None,
        "bandwidth": None,
    }

    fetchers = {
        "server": _fetch_server_info,
        "libraries": _fetch_libraries,
        "sessions": _fetch_sessions,
        "recently_added": _fetch_recently_added,
        "on_deck": _fetch_on_deck,
        "history": _fetch_history,
        "bandwidth": _fetch_bandwidth_stats,
    }

    with ThreadPoolExecutor(max_workers=7) as pool:
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

    results["has_token"] = bool(_plex_token())
    return results


def get_plex_sessions():
    """Fetch only session data (for the fast-refresh endpoint)."""
    if not _plex_host() or not _plex_token():
        return {"sessions": None, "has_token": bool(_plex_token())}
    data = _fetch_sessions()
    return {"sessions": data, "has_token": bool(_plex_token())}


def auto_detect_plex_token():
    """SSH to NAS and find Plex token from Preferences.xml."""
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

    # Common Plex Preferences.xml paths on Synology
    search_paths = [
        "/volume1/PlexMediaServer/AppData/Plex Media Server/Preferences.xml",
        "/volume1/Plex/Library/Application Support/Plex Media Server/Preferences.xml",
        "/volume1/@appdata/Plex Media Server/Preferences.xml",
        "/volume2/PlexMediaServer/AppData/Plex Media Server/Preferences.xml",
    ]

    token = None
    found_path = None

    for path in search_paths:
        try:
            stdin, stdout, stderr = client.exec_command(f'cat "{path}"', timeout=10)
            content = stdout.read().decode("utf-8", errors="replace")
            if content and "PlexOnlineToken" in content:
                match = re.search(r'PlexOnlineToken="([^"]+)"', content)
                if match:
                    token = match.group(1)
                    found_path = path
                    break
        except Exception:
            continue

    # If not found in known paths, try find command
    if not token:
        try:
            stdin, stdout, stderr = client.exec_command(
                'find /volume1 /volume2 -name "Preferences.xml" -path "*/Plex Media Server/*" 2>/dev/null | head -5',
                timeout=15,
            )
            paths = stdout.read().decode("utf-8", errors="replace").strip().split("\n")
            for path in paths:
                path = path.strip()
                if not path:
                    continue
                stdin, stdout, stderr = client.exec_command(f'cat "{path}"', timeout=10)
                content = stdout.read().decode("utf-8", errors="replace")
                if content and "PlexOnlineToken" in content:
                    match = re.search(r'PlexOnlineToken="([^"]+)"', content)
                    if match:
                        token = match.group(1)
                        found_path = path
                        break
        except Exception:
            pass

    client.close()

    if not token:
        return {"success": False, "error": "Could not find PlexOnlineToken in Preferences.xml"}

    # Save token and host to .env
    from .settings import update_env_key
    update_env_key("PLEX_TOKEN", token)
    if not os.environ.get("PLEX_HOST"):
        update_env_key("PLEX_HOST", nas_host)

    return {
        "success": True,
        "message": f"Token found in {found_path}",
        "token": token[:8] + "..." + token[-4:] if len(token) > 12 else "***",
    }
