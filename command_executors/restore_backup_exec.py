"""Restore a file to its pre-operation state from a unified `.diff` backup."""

from __future__ import annotations

from infrastructure.backups import restore_backup
from infrastructure.workspace import resolve_workspace_path


def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    backup_filename = attributes.get("backup_filename")
    if not backup_filename and isinstance(content, dict):
        val = content.get("BackupFilename", "")
        backup_filename = val[0] if isinstance(val, list) else str(val)
    elif not backup_filename and isinstance(content, str):
        backup_filename = content.strip()

    if not backup_filename:
        return "[Error] RestoreBackup requires a 'backup_filename' attribute or <BackupFilename> tag."

    workspace_root, _ = resolve_workspace_path(".", context_state.get("workspace_root"))
    try:
        return restore_backup(workspace_root, backup_filename)
    except Exception as e:
        return f"[Error] Failed to restore backup '{backup_filename}': {str(e)}"
