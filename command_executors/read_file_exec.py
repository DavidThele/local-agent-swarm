from infrastructure.workspace import is_within_workspace, request_file_access, resolve_workspace_path


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


def _format_numbered_lines(lines: list[str], start_line_num: int, max_line_num: int) -> str:
    width = max(len(str(max_line_num)), 1)
    formatted = []
    for offset, line in enumerate(lines):
        line_num = start_line_num + offset
        formatted.append(f"{line_num:>{width}} | {line}")
    return "".join(formatted)


def execute(attributes: dict, content: dict, context_state: dict) -> str:
    path = attributes.get("path")
    start_raw = attributes.get("start_line")
    end_raw = attributes.get("end_line")

    if not path:
        return "[Error] File path is required."

    workspace_root, target_path = resolve_workspace_path(
        path, context_state.get("workspace_root")
    )
    if not is_within_workspace(target_path, workspace_root):
        if not request_file_access("read", target_path):
            return f"[FILE_ACCESS_DENIED] Read denied for {target_path}."

    if not target_path.exists():
        return f"[Error] File not found at path: {path}"

    try:
        start_line = _parse_optional_line(start_raw, "start_line")
        end_line = _parse_optional_line(end_raw, "end_line")
    except ValueError as e:
        return f"[Error] {e}"

    if start_line is not None and end_line is not None and end_line < start_line:
        return f"[Error] end_line ({end_line}) cannot be less than start_line ({start_line})."

    try:
        with open(target_path, "r", encoding="utf-8") as f:
            lines = f.readlines()

        total_lines = len(lines)
        if total_lines == 0:
            return f"--- File Contents ({target_path}, 0 lines) ---\n"

        if start_line is not None or end_line is not None:
            actual_start = start_line if start_line is not None else 1
            actual_end = min(total_lines, end_line) if end_line is not None else total_lines

            if actual_start > total_lines:
                return (
                    f"[Error] start_line ({actual_start}) exceeds total line count "
                    f"({total_lines}) for {target_path}."
                )

            selected = lines[actual_start - 1 : actual_end]
            body = _format_numbered_lines(selected, actual_start, total_lines)
            return (
                f"--- File Snippet ({target_path}, lines {actual_start}-{actual_end} of {total_lines}) ---\n"
                f"{body}"
            )

        body = _format_numbered_lines(lines, 1, total_lines)
        return f"--- File Contents ({target_path}, {total_lines} lines) ---\n{body}"

    except Exception as e:
        return f"[Error] Could not read file {path}: {str(e)}"
