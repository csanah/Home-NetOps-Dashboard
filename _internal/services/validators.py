"""Input validation for user-facing endpoints."""
from __future__ import annotations

import re

from services.settings import SETTINGS_SCHEMA

_VALID_SECTIONS = set(SETTINGS_SCHEMA.keys())

# All known test_connection system identifiers
_VALID_SYSTEMS = {
    "udm_api", "udm_ssh", "proxmox_api", "proxmox_ssh",
    "ha_api", "nas_ssh", "bike_ssh", "media_ssh",
    "sabnzbd", "sonarr", "radarr", "prowlarr",
    "plex_api", "overseerr_api",
}


def validate_section_id(section_id: str) -> bool:
    """Check section_id is a known settings section."""
    return section_id in _VALID_SECTIONS


def validate_system_id(system: str) -> bool:
    """Check system is a known test_connection target."""
    return system in _VALID_SYSTEMS


def validate_settings_values(section_id: str, data: dict) -> dict | None:
    """Validate settings values for type and length. Returns error dict or None."""
    schema = SETTINGS_SCHEMA.get(section_id)
    if not schema:
        return {"error": "Unknown section"}

    for field in schema["fields"]:
        key = field["key"]
        if key not in data:
            continue
        value = str(data[key])
        # Max length check
        if len(value) > 1000:
            return {"error": f"Value for {field['label']} exceeds maximum length"}
        # Number type check
        if field.get("type") == "number" and value:
            try:
                int(value)
            except ValueError:
                return {"error": f"{field['label']} must be a number"}
    return None


def sanitize_search_query(query: str) -> str:
    """Strip potentially dangerous characters from search queries."""
    # Remove control characters and null bytes
    query = re.sub(r'[\x00-\x1f\x7f]', '', query)
    # Limit length
    return query[:200]
