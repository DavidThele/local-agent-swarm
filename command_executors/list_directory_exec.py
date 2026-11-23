from pathlib import Path
from infrastructure.workspace import (
    IGNORED_DIRS,
    is_within_workspace,
    resolve_workspace_path,
)

LARGE_FILE_THRESHOLD_BYTES = 3 * 1024 * 1024  # 3 MB


def _format_size(num_bytes: int) -> str:
    if num_bytes < 1024:
        return f"{num_bytes} B"
    size = float(num_bytes)
    for unit in ("KB", "MB", "GB", "TB"):
        size /= 1024.0
        if size < 1024.0 or unit == "TB":
            return f"{size:.1f} {unit}"
    return f"{num_bytes} B"


def _is_binary_file(file_path: Path, sample_size: int = 8192) -> bool:
    try:
        with open(file_path, "rb") as f:
            chunk = f.read(sample_size)
        if not chunk:
            return False
        if b"\x00" in chunk:
            return True
        try:
            chunk.decode("utf-8")
            return False
        except UnicodeDecodeError:
            # Allow a small number of partial multi-byte UTF-8 boundary bytes at end of chunk
            for trim in range(1, min(4, len(chunk)) + 1):
                try:
                    chunk[:-trim].decode("utf-8")
                    return False
                except UnicodeDecodeError:
                    continue
            return True
    except OSError:
        return True


def _count_lines(file_path: Path) -> int:
    newline_count = 0
    total_bytes = 0
    last_byte = b""
    with open(file_path, "rb") as f:
        while True:
            chunk = f.read(65536)
            if not chunk:
                break
            total_bytes += len(chunk)
            newline_count += chunk.count(b"\n")
            last_byte = chunk[-1:]
    if total_bytes == 0:
        return 0
    return newline_count if last_byte == b"\n" else newline_count + 1


def _describe_file(file_path: Path) -> str:
    try:
        size = file_path.stat().st_size
    except OSError:
        return "(size unavailable)"

    size_str = _format_size(size)
    if size > LARGE_FILE_THRESHOLD_BYTES:
        return f"({size_str}, >3 MB - WARNING: large file, avoid reading directly)"

    if _is_binary_file(file_path):
        return f"({size_str}, binary)"

    try:
        line_count = _count_lines(file_path)
        unit = "line" if line_count == 1 else "lines"
        return f"({size_str}, {line_count} {unit})"
    except OSError:
        return f"({size_str}, lines unavailable)"


def get_tree(dir_path: Path, current_depth: int, max_depth: int) -> list[str]:
    if current_depth > max_depth:
        return []

    results: list[str] = []
    try:
        entries = sorted(
            dir_path.iterdir(),
            key=lambda p: (not p.is_dir(), p.name.lower()),
        )
        for item in entries:
            if item.name in IGNORED_DIRS:
                continue
            if item.is_dir():
                results.append(f"{'  ' * current_depth}[DIR] {item.name}/")
                results.extend(get_tree(item, current_depth + 1, max_depth))
            else:
                meta = _describe_file(item)
                results.append(f"{'  ' * current_depth}[FILE] {item.name} {meta}")
    except PermissionError:
        results.append(f"{'  ' * current_depth}[Permission Denied]")

    return results


def execute(attributes: dict, content: dict, context_state: dict) -> str:
    path = attributes.get("path")
    try:
        depth = int(attributes.get("depth", 1))
    except (TypeError, ValueError):
        return "[Error] ListDirectory depth must be an integer."
    if depth < 0:
        return "[Error] ListDirectory depth must be non-negative."

    if not path:
        return "[Error] Directory path is required."

    workspace_root, target_path = resolve_workspace_path(
        path, context_state.get("workspace_root")
    )
    if not is_within_workspace(target_path, workspace_root):
        return f"[Error] Directory is outside the authorized workspace: {target_path}"

    if not target_path.exists():
        return f"[Error] Directory not found: {path}"

    target_dir = target_path
    if not target_dir.is_dir():
        return f"[Error] Path is not a directory: {path}"

    tree = get_tree(target_dir, 0, depth)
    return "\n".join(tree)
