"""Surgical exact search-and-replace file editor with stale line-range shift projection."""

from __future__ import annotations

import difflib
import uuid
from pathlib import Path

from infrastructure.backups import (
    check_mutation_allowed,
    get_edit_history,
    get_session_id,
    project_line_range,
    record_edit_shift,
    save_backup_diff,
)
from infrastructure.workspace import (
    is_within_workspace,
    request_file_access,
    resolve_workspace_path,
)


def _parse_optional_line(value, label: str) -> int | None:
    if value is None or str(value).strip() == "":
        return None
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer, got {value!r}.")
    if parsed < 1:
        raise ValueError(f"{label} must be >= 1, got {parsed}.")
    return parsed


def _slice_line_window(
    lines: list[str],
    start_line: int | None,
    end_line: int | None,
) -> tuple[int, int, str, str, str]:
    total = len(lines)
    s = 1 if start_line is None else max(1, min(start_line, total))
    e = total if end_line is None else max(s, min(end_line, total))
    prefix = "".join(lines[: s - 1])
    window = "".join(lines[s - 1 : e])
    suffix = "".join(lines[e:])
    return s, e, prefix, window, suffix


def _first_str(val) -> str:
    if isinstance(val, list):
        return str(val[0]) if val else ""
    return "" if val is None else str(val)


def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    target_path = attributes.get("path")
    worker_id = context_state.get("worker_id", uuid.uuid4().hex[:8])

    if not target_path:
        return "[Error] EditFile requires a 'path' attribute."

    if isinstance(content, dict):
        old_str = _first_str(content.get("OldStr", content.get("Search", "")))
        new_str = _first_str(content.get("NewStr", content.get("Replace", "")))
        summary = _first_str(content.get("Summary", "Applied surgical edit."))
    else:
        return "[Error] EditFile requires <OldStr> and <NewStr> child tags."

    if not old_str:
        return "[Error] old_str (<OldStr>) must not be empty."

    try:
        start_line = _parse_optional_line(attributes.get("start_line"), "start_line")
        end_line = _parse_optional_line(attributes.get("end_line"), "end_line")
        if start_line is not None and end_line is not None and end_line < start_line:
            return f"[Error] end_line ({end_line}) must be >= start_line ({start_line})."

        workspace_root, target_file = resolve_workspace_path(
            target_path, context_state.get("workspace_root")
        )
        check_mutation_allowed(target_file, workspace_root)

        if not target_file.exists():
            return f"[Error] File not found: {target_path}"
        if not target_file.is_file():
            return f"[Error] Path is a directory, not a file: {target_path}"

        old_content = target_file.read_text(encoding="utf-8")
        file_key = str(target_file)
        adjusted_note = ""
        range_label = ""

        if start_line is None and end_line is None:
            occurrences = old_content.count(old_str)
            if occurrences == 0:
                return (
                    f"[Error] old_str not found in '{target_path}'. "
                    "Verify exact whitespace and indentation."
                )
            if occurrences > 1:
                return (
                    f"[Error] Ambiguous edit: old_str matched {occurrences} times in '{target_path}'. "
                    "Provide more surrounding context or pass start_line/end_line."
                )
            match_idx = old_content.index(old_str)
            new_content = old_content.replace(old_str, new_str, 1)
        else:
            lines = old_content.splitlines(keepends=True)
            if not lines:
                return f"[Error] File '{target_path}' is empty."

            s, e, prefix, window, suffix = _slice_line_window(lines, start_line, end_line)
            occurrences = window.count(old_str)

            if occurrences > 1:
                return (
                    f"[Error] Ambiguous edit: old_str matched {occurrences} times in '{target_path}' "
                    f"(lines {s}-{e}). Narrow the line range or provide more surrounding context."
                )

            if occurrences == 0:
                history = get_edit_history(file_key)
                tried: set[tuple[int, int]] = {(s, e)}
                found_fallback = False

                for idx in range(len(history)):
                    cand_s, cand_e = project_line_range(start_line, end_line, history[idx:])
                    fs, fe, f_prefix, f_window, f_suffix = _slice_line_window(lines, cand_s, cand_e)
                    if (fs, fe) in tried:
                        continue
                    tried.add((fs, fe))
                    if f_window.count(old_str) == 1:
                        adjusted_note = f" (adjusted from {s}-{e} to {fs}-{fe} after prior edits)"
                        s, e, prefix, window, suffix = fs, fe, f_prefix, f_window, f_suffix
                        found_fallback = True
                        break

                if not found_fallback:
                    total_matches = old_content.count(old_str)
                    hint = ""
                    if total_matches == 1:
                        actual_line = old_content.count("\n", 0, old_content.index(old_str)) + 1
                        hint = f" Note: old_str exists uniquely elsewhere at line {actual_line}."
                    elif total_matches > 1:
                        hint = f" Note: old_str exists {total_matches} times outside lines {s}-{e}."
                    return f"[Error] old_str not found in '{target_path}' within lines {s}-{e}.{hint}"

            match_idx = len(prefix) + window.index(old_str)
            new_window = window.replace(old_str, new_str, 1)
            new_content = prefix + new_window + suffix
            range_label = f" lines {s}-{e}{adjusted_note}"

        def build_diff() -> str:
            diff = difflib.unified_diff(
                old_content.splitlines(keepends=True),
                new_content.splitlines(keepends=True),
                fromfile=str(target_file),
                tofile=str(target_file),
            )
            return "".join(diff) or "[File Access] No content changes."

        if not is_within_workspace(target_file, workspace_root):
            if not request_file_access("edit", target_file, build_diff, agent_id=worker_id):
                return f"[FILE_ACCESS_DENIED] Edit denied for {target_file}."

        session_id = get_session_id(context_state)
        backup_rel = save_backup_diff(
            workspace_root,
            session_id,
            "edit",
            target_file,
            old_content,
            new_content,
        )

        target_file.write_text(new_content, encoding="utf-8")
        delta = record_edit_shift(file_key, old_content, match_idx, old_str, new_str)

        local_chat_dir = context_state.get("local_chat_dir")
        if local_chat_dir:
            chat_dir = Path(local_chat_dir)
            chat_dir.mkdir(parents=True, exist_ok=True)
            with open(chat_dir / f"{worker_id}_summary.txt", "a", encoding="utf-8") as f:
                f.write(f"Edited File: {target_path}\nSummary: {summary}\n---\n")

        backup_note = f" Backup saved: .backups/{backup_rel}" if backup_rel else ""
        return f"Edited '{target_path}'{range_label} (line delta: {delta:+d}).{backup_note}"

    except Exception as e:
        return f"[Error] Failed to edit file {target_path}: {str(e)}"
