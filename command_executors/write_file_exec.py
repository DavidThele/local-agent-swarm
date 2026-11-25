import difflib
import uuid
from pathlib import Path

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
        return "[Error] WriteFile requires a 'path' attribute."

    if isinstance(content, dict):
        summary_val = content.get("Summary", "Overwrote file.")
        summary = summary_val[0] if isinstance(summary_val, list) else str(summary_val)
        raw_content = content.get("Content", "")
        file_content = raw_content[0] if isinstance(raw_content, list) else str(raw_content)
    else:
        file_content = str(content)
        summary = "Wrote raw content."

    try:
        workspace_root, target_file = resolve_workspace_path(
            target_path, context_state.get("workspace_root")
        )
        check_mutation_allowed(target_file, workspace_root)

        is_new = not target_file.exists()
        old_content = "" if is_new else target_file.read_text(encoding="utf-8")

        def build_diff() -> str:
            diff = difflib.unified_diff(
                old_content.splitlines(keepends=True),
                file_content.splitlines(keepends=True),
                fromfile=str(target_file),
                tofile=str(target_file),
            )
            return "".join(diff) or "[File Access] No content changes."

        if not is_within_workspace(target_file, workspace_root):
            if not request_file_access("write", target_file, build_diff, agent_id=worker_id):
                return f"[FILE_ACCESS_DENIED] Write denied for {target_file}."

        session_id = get_session_id(context_state)
        backup_rel = save_backup_diff(
            workspace_root,
            session_id,
            "write",
            target_file,
            old_content,
            file_content,
            is_new_file=is_new,
        )

        target_file.parent.mkdir(parents=True, exist_ok=True)
        target_file.write_text(file_content, encoding="utf-8")
        clear_edit_history(str(target_file))

        local_chat_dir = context_state.get("local_chat_dir")
        if local_chat_dir:
            chat_dir = Path(local_chat_dir)
            chat_dir.mkdir(parents=True, exist_ok=True)
            with open(chat_dir / f"{worker_id}_full.txt", "a", encoding="utf-8") as f:
                f.write(f"=== Target Path: {target_path} (mode=overwrite) ===\n{file_content}\n\n")
            with open(chat_dir / f"{worker_id}_summary.txt", "a", encoding="utf-8") as f:
                f.write(f"Modified File: {target_path}\nSummary: {summary}\n---\n")

        verb = "Created" if is_new else "Overwrote"
        backup_note = f" Backup saved: .backups/{backup_rel}" if backup_rel else ""
        return f"[Success] {verb} '{target_path}' ({len(file_content)} chars).{backup_note} Summary: {summary}"

    except Exception as e:
        return f"[Error] Failed to write file {target_path}: {str(e)}"
