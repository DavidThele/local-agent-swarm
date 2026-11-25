"""List recent session-organized unified-diff backups in `.backups/`."""

from __future__ import annotations

from infrastructure.backups import list_backups
from infrastructure.workspace import resolve_workspace_path
from runtime import DEFAULT_LIST_BACKUPS_LIMIT


def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    limit_raw = attributes.get("limit", DEFAULT_LIST_BACKUPS_LIMIT)
    session_id = attributes.get("session_id") or None
    try:
        limit = int(limit_raw)
    except (TypeError, ValueError):
        return f"[Error] ListBackups limit must be an integer, got {limit_raw!r}."

    workspace_root, _ = resolve_workspace_path(".", context_state.get("workspace_root"))
    try:
        return list_backups(workspace_root, limit=limit, session_id=session_id)
    except Exception as e:
        return f"[Error] Failed to list backups: {str(e)}"
