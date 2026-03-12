import os
import re
from pathlib import Path

from runtime import PROJECT_ROOT
_project_root = PROJECT_ROOT
TEMPLATE_PATH = _project_root / "claude-template.md"
OUTPUT_PATH = _project_root / "CLAUDE.md"


def generate_claude_md():
    """Render claude-template.md -> CLAUDE.md using env vars. Returns content or None."""
    if not TEMPLATE_PATH.exists():
        return None
    content = TEMPLATE_PATH.read_text(encoding="utf-8")
    # Replace {{KEY}} with os.environ value or leave placeholder if unset
    content = re.sub(
        r"\{\{(\w+)\}\}",
        lambda m: os.environ.get(m.group(1), m.group(0)),
        content,
    )
    OUTPUT_PATH.write_text(content, encoding="utf-8")
    # Reload relay system prompt
    try:
        from .claude_relay import reload_system_prompt
        reload_system_prompt()
    except Exception:
        pass
    return content
