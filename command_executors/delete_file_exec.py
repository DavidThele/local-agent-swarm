"""Delete a file after saving its unified-diff backup in `.backups/<session>/`."""

from __future__ import annotations

import uuid

from infrastructure.backups import (
    check_mutation_allowed,
    clear_edit_history,
    get_session_id,
    save_backup_diff,
)
from infrastructure.workspace import (
    is_within_workspace,
    request_file_access,
    resolve_workspace_path,
)


def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    target_path = attributes.get("path")
    worker_id = context_state.get("worker_id", uuid.uuid4().hex[:8])

    if not target_path:
        return "[Error] DeleteFile requires a 'path' attribute."

    try:
        workspace_root, target_file = resolve_workspace_path(
            target_path, context_state.get("workspace_root")
        )
        check_mutation_allowed(target_file, workspace_root)

        if not target_file.exists():
            return f"[Error] File not found: {target_path}"
        if not target_file.is_file():
            return f"[Error] Path is a directory, not a file: {target_path}"

        if not is_within_workspace(target_file, workspace_root):
            if not request_file_access("delete", target_file, agent_id=worker_id):
                return f"[FILE_ACCESS_DENIED] Delete denied for {target_file}."

        old_content = target_file.read_text(encoding="utf-8", errors="replace")
        session_id = get_session_id(context_state)
        backup_rel = save_backup_diff(
            workspace_root,
            session_id,
            "delete",
            target_file,
            old_content,
            "",
            is_delete=True,
        )

        target_file.unlink()
        clear_edit_history(str(target_file))

        backup_note = f" Backup saved: .backups/{backup_rel}" if backup_rel else ""
        return f"Deleted '{target_path}'.{backup_note}"

    except Exception as e:
        return f"[Error] Failed to delete file {target_path}: {str(e)}"
