import uuid
import difflib
from pathlib import Path
from infrastructure.workspace import is_within_workspace, request_file_access, resolve_workspace_path


def _normalize_lines(text: str) -> list[str]:
    """Converts a text block into newline-terminated lines for clean splicing."""
    if text == "":
        return []
    lines = text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += "\n"
    return lines


def _parse_int(value, label: str) -> int:
    try:
        parsed = int(str(value).strip())
    except (TypeError, ValueError):
        raise ValueError(f"{label} must be an integer, got {value!r}.")
    if parsed < 1:
        raise ValueError(f"{label} must be >= 1, got {parsed}.")
    return parsed


def _apply_line_edits(original_text: str, edits: list[dict]) -> str:
    """
    Applies one or more 1-based line insert/replace operations against original_text.
    Edits are validated against the original line count and applied in descending line
    order so earlier line numbers never shift subsequent edits in the same batch.
    """
    lines = original_text.splitlines(keepends=True)
    if lines and not lines[-1].endswith(("\n", "\r")):
        lines[-1] += "\n"
    total_lines = len(lines)

    normalized_ops = []
    for idx, edit in enumerate(edits):
        action = str(edit.get("action", "")).strip().lower()
        new_text = edit.get("content", "")
        if isinstance(new_text, list):
            new_text = "\n".join(str(x) for x in new_text)
        new_lines = _normalize_lines(str(new_text))

        if action == "insert":
            line_num = _parse_int(edit.get("line"), f"Edit #{idx + 1} line")
            # Allow inserting up to total_lines + 1 (append at end of file)
            clamped = min(line_num, total_lines + 1)
            normalized_ops.append({
                "action": "insert",
                "start": clamped,
                "end": clamped,
                "new_lines": new_lines,
                "order": idx,
            })
        elif action == "replace":
            start_line = _parse_int(edit.get("start_line"), f"Edit #{idx + 1} start_line")
            end_raw = edit.get("end_line")
            end_line = start_line if end_raw in (None, "") else _parse_int(end_raw, f"Edit #{idx + 1} end_line")
            if end_line < start_line:
                raise ValueError(f"Edit #{idx + 1}: end_line ({end_line}) < start_line ({start_line}).")
            if total_lines == 0 or start_line > total_lines or end_line > total_lines:
                raise ValueError(
                    f"Edit #{idx + 1}: line range {start_line}-{end_line} out of bounds "
                    f"(file has {total_lines} lines)."
                )
            normalized_ops.append({
                "action": "replace",
                "start": start_line,
                "end": end_line,
                "new_lines": new_lines,
                "order": idx,
            })
        else:
            raise ValueError(f"Edit #{idx + 1}: unsupported action {action!r}; expected 'insert' or 'replace'.")

    # Sort descending by start line (and reverse order for ties) so bottom-up edits preserve indices
    normalized_ops.sort(key=lambda op: (op["start"], op["order"]), reverse=True)

    for op in normalized_ops:
        if op["action"] == "insert":
            insert_idx = op["start"] - 1
            lines[insert_idx:insert_idx] = op["new_lines"]
        else:
            start_idx = op["start"] - 1
            end_idx = op["end"]
            lines[start_idx:end_idx] = op["new_lines"]

    return "".join(lines)


def _extract_edits(attributes: dict, content: dict | str) -> tuple[str, list[dict] | None, str, str]:
    """
    Returns (mode, edits_or_None, full_file_content, summary).
    """
    mode = str(attributes.get("mode", "overwrite")).strip().lower()
    summary = "No summary provided."
    full_content = ""

    if isinstance(content, dict):
        summary_val = content.get("Summary", summary)
        summary = summary_val[0] if isinstance(summary_val, list) else str(summary_val)

        # Case 1: Batched <Edits><Edit>...</Edit></Edits>
        raw_edits_block = content.get("Edits")
        if raw_edits_block is not None:
            raw_list = raw_edits_block.get("Edit", []) if isinstance(raw_edits_block, dict) else []
            if isinstance(raw_list, dict):
                raw_list = [raw_list]
            edits = []
            for item in raw_list:
                if not isinstance(item, dict):
                    continue
                edits.append({
                    "action": item.get("Action", ""),
                    "line": item.get("Line"),
                    "start_line": item.get("StartLine"),
                    "end_line": item.get("EndLine"),
                    "content": item.get("Content", ""),
                })
            return "edits", edits, "", summary

        raw_content = content.get("Content", "")
        full_content = raw_content[0] if isinstance(raw_content, list) else str(raw_content)
    else:
        full_content = str(content)
        summary = "Wrote raw content."

    # Case 2: Single-edit via <WriteFile mode="insert" line="N"> or mode="replace"
    if mode in {"insert", "replace"}:
        single_edit = {
            "action": mode,
            "line": attributes.get("line"),
            "start_line": attributes.get("start_line") or attributes.get("line"),
            "end_line": attributes.get("end_line"),
            "content": full_content,
        }
        return mode, [single_edit], "", summary

    # Case 3: Standard full-file overwrite
    return "overwrite", None, full_content, summary


def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    target_path = attributes.get("path")
    chat_dir = Path(context_state.get("local_chat_dir", ".agents/chats/default"))
    worker_id = context_state.get("worker_id", uuid.uuid4().hex[:8])

    if not target_path:
        return "[Error] WriteFile requires a 'path' attribute."

    try:
        mode, edits, file_content, summary = _extract_edits(attributes, content)

        workspace_root, target_file = resolve_workspace_path(
            target_path, context_state.get("workspace_root")
        )

        if edits is not None:
            if not edits:
                return "[Error] WriteFile <Edits> block contained no valid <Edit> entries."
            if not target_file.exists():
                if mode == "insert":
                    old_content = ""
                else:
                    return f"[Error] Cannot edit non-existent file: {target_path}"
            else:
                old_content = target_file.read_text(encoding="utf-8")

            final_content = _apply_line_edits(old_content, edits)
        else:
            try:
                old_content = target_file.read_text(encoding="utf-8")
            except FileNotFoundError:
                old_content = ""
            final_content = file_content

        def build_diff() -> str:
            diff = difflib.unified_diff(
                old_content.splitlines(keepends=True),
                final_content.splitlines(keepends=True),
                fromfile=str(target_file),
                tofile=str(target_file),
            )
            return "".join(diff) or "[File Access] No content changes."

        if not is_within_workspace(target_file, workspace_root):
            if not request_file_access("write", target_file, build_diff, agent_id=worker_id):
                return f"[FILE_ACCESS_DENIED] Write denied for {target_file}."

        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(final_content)

        chat_dir.mkdir(parents=True, exist_ok=True)

        full_log_path = chat_dir / f"{worker_id}_full.txt"
        with open(full_log_path, "a", encoding="utf-8") as f:
            f.write(f"=== Target Path: {target_path} (mode={mode}) ===\n{final_content}\n\n")

        summary_log_path = chat_dir / f"{worker_id}_summary.txt"
        with open(summary_log_path, "a", encoding="utf-8") as f:
            f.write(f"Modified File: {target_path}\nSummary: {summary}\n---\n")

        return f"[Success] File updated ({mode}) at {target_path}. Summary: {summary}"

    except Exception as e:
        return f"[Error] Failed to write file {target_path}: {str(e)}"