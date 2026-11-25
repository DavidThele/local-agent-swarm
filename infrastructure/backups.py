"""Session-organized unified-diff backup management, .gitignore filtering, and edit-shift tracking."""

from __future__ import annotations

import fnmatch
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from infrastructure.diff_engine import generate_unified_diff, parse_unified_diff
from runtime import MAX_EDIT_HISTORY_PER_FILE

_PROCESS_DEFAULT_SESSION = f"session_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


@dataclass(frozen=True)
class EditShift:
    start_line: int
    end_line: int
    delta: int


_EDIT_HISTORY_LOCK = threading.Lock()
_EDIT_HISTORY: dict[str, list[EditShift]] = {}


def sanitize_session_id(raw: str | None) -> str:
    if not raw or not str(raw).strip():
        return _PROCESS_DEFAULT_SESSION
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", str(raw).strip()).strip("._-")
    return cleaned[:80] or _PROCESS_DEFAULT_SESSION


def get_session_id(context_state: dict | None) -> str:
    if not isinstance(context_state, dict):
        return _PROCESS_DEFAULT_SESSION
    explicit = context_state.get("session_id")
    if explicit:
        return sanitize_session_id(str(explicit))
    chat_dir = context_state.get("local_chat_dir")
    if chat_dir:
        name = Path(str(chat_dir)).name
        if name:
            return sanitize_session_id(name)
    return _PROCESS_DEFAULT_SESSION


# -----------------------------------------------------------------------------
# Edit-shift projection for surgical line-scoped edits
# -----------------------------------------------------------------------------

def record_edit_shift(
    file_key: str,
    old_content: str,
    match_char_idx: int,
    old_str: str,
    new_str: str,
) -> int:
    start_line = old_content.count("\n", 0, match_char_idx) + 1
    old_newlines = old_str.count("\n")
    end_line = start_line + (
        old_newlines - 1
        if old_str.endswith("\n") and old_newlines > 0
        else old_newlines
    )
    delta = new_str.count("\n") - old_newlines
    if delta != 0:
        with _EDIT_HISTORY_LOCK:
            history = _EDIT_HISTORY.setdefault(file_key, [])
            history.append(EditShift(start_line=start_line, end_line=end_line, delta=delta))
            if len(history) > MAX_EDIT_HISTORY_PER_FILE:
                del history[:-MAX_EDIT_HISTORY_PER_FILE]
    return delta


def get_edit_history(file_key: str) -> list[EditShift]:
    with _EDIT_HISTORY_LOCK:
        return list(_EDIT_HISTORY.get(file_key, []))


def clear_edit_history(file_key: str) -> None:
    with _EDIT_HISTORY_LOCK:
        _EDIT_HISTORY.pop(file_key, None)


def project_line_range(
    start_line: int | None,
    end_line: int | None,
    shifts: list[EditShift],
) -> tuple[int | None, int | None]:
    """Project stale 1-indexed line bounds forward through subsequent edits."""
    s, e = start_line, end_line
    for shift in shifts:
        if s is not None:
            if s > shift.end_line:
                s = max(1, s + shift.delta)
            elif s >= shift.start_line:
                s = shift.start_line
        if e is not None:
            if e >= shift.start_line:
                e = max(shift.start_line, e + shift.delta)
    if s is not None and e is not None and e < s:
        e = s
    return s, e


# -----------------------------------------------------------------------------
# .gitignore matching
# -----------------------------------------------------------------------------

def _load_gitignore_rules(workspace_root: Path) -> list[tuple[bool, bool, str]]:
    """
    Parse `<workspace_root>/.gitignore` into a list of (negated, dir_only, pattern).
    """
    gitignore_path = workspace_root / ".gitignore"
    if not gitignore_path.is_file():
        return []

    rules: list[tuple[bool, bool, str]] = []
    try:
        raw_lines = gitignore_path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []

    for line in raw_lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        negated = False
        if stripped.startswith("!"):
            negated = True
            stripped = stripped[1:]
        dir_only = stripped.endswith("/")
        if dir_only:
            stripped = stripped.rstrip("/")
        if not stripped:
            continue
        rules.append((negated, dir_only, stripped))
    return rules


def _match_gitignore_pattern(rel_posix: str, parts: tuple[str, ...], pattern: str, dir_only: bool) -> bool:
    anchored = pattern.startswith("/")
    clean_pat = pattern.lstrip("/")
    has_slash = "/" in clean_pat

    if dir_only:
        # Must match a directory prefix of the file path
        dir_parts = parts[:-1]
        if not dir_parts:
            return False
        if anchored or has_slash:
            for idx in range(1, len(dir_parts) + 1):
                prefix = "/".join(dir_parts[:idx])
                if fnmatch.fnmatch(prefix, clean_pat):
                    return True
            return False
        return any(fnmatch.fnmatch(seg, clean_pat) for seg in dir_parts)

    if anchored:
        return fnmatch.fnmatch(rel_posix, clean_pat) or any(
            fnmatch.fnmatch("/".join(parts[:idx]), clean_pat) for idx in range(1, len(parts))
        )

    if has_slash:
        if fnmatch.fnmatch(rel_posix, clean_pat):
            return True
        # Also allow matching against any trailing subpath or directory prefix
        for start in range(len(parts)):
            sub = "/".join(parts[start:])
            if fnmatch.fnmatch(sub, clean_pat):
                return True
        return False

    # Basename / any segment match
    return any(fnmatch.fnmatch(seg, clean_pat) for seg in parts)


def is_gitignored(target_path: Path, workspace_root: Path) -> bool:
    """Return True if `target_path` matches a rule in `<workspace_root>/.gitignore`."""
    try:
        rel = target_path.resolve().relative_to(workspace_root.resolve())
    except ValueError:
        return False

    parts = rel.parts
    if not parts:
        return False
    if ".git" in parts or ".backups" in parts:
        return True

    rules = _load_gitignore_rules(workspace_root)
    if not rules:
        return False

    rel_posix = rel.as_posix()
    ignored = False
    for negated, dir_only, pattern in rules:
        if _match_gitignore_pattern(rel_posix, parts, pattern, dir_only):
            ignored = not negated
    return ignored


# -----------------------------------------------------------------------------
# Protected mutation paths & session-organized backup operations
# -----------------------------------------------------------------------------

def check_mutation_allowed(target_path: Path, workspace_root: Path) -> None:
    """Raise PermissionError if mutating `.backups/`, `.env`, or the workspace root itself."""
    resolved_root = workspace_root.resolve()
    resolved_target = target_path.resolve()
    try:
        rel = resolved_target.relative_to(resolved_root)
    except ValueError:
        # Outside workspace: handled separately by request_file_access()
        if resolved_target.name == ".env":
            raise PermissionError("Direct modification of '.env' is forbidden.")
        return

    if not rel.parts:
        raise PermissionError("Cannot directly mutate the workspace root directory.")
    if ".backups" in rel.parts:
        raise PermissionError(
            "Direct modification of '.backups/' is forbidden. Use restore_backup instead."
        )
    if rel == Path(".env") or rel.name == ".env":
        raise PermissionError("Direct modification of '.env' is forbidden.")


def save_backup_diff(
    workspace_root: Path,
    session_id: str,
    action: str,
    target_path: Path,
    old_content: str,
    new_content: str,
    *,
    is_new_file: bool = False,
    is_delete: bool = False,
) -> str | None:
    """
    Write a unified diff to `<workspace_root>/.backups/<session_id>/`.
    Skips backup creation and returns None if `target_path` is excluded by `.gitignore`
    or lies outside `workspace_root`.
    Returns the backup path relative to `.backups/` (e.g. `<session_id>/<file>.diff`).
    """
    resolved_root = workspace_root.resolve()
    resolved_target = target_path.resolve()
    try:
        rel_path = resolved_target.relative_to(resolved_root).as_posix()
    except ValueError:
        return None

    if is_gitignored(resolved_target, resolved_root):
        return None

    safe_session = sanitize_session_id(session_id)
    session_dir = resolved_root / ".backups" / safe_session
    session_dir.mkdir(parents=True, exist_ok=True)

    diff_text = generate_unified_diff(
        old_content,
        new_content,
        rel_path,
        is_new_file=is_new_file,
        is_delete=is_delete,
    )

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    flattened = rel_path.replace("/", "__").replace("\\", "__")
    base_name = f"{timestamp}_{action}_{flattened}"
    backup_path = session_dir / f"{base_name}.diff"

    counter = 1
    while backup_path.exists():
        backup_path = session_dir / f"{base_name}_{counter}.diff"
        counter += 1

    backup_path.write_text(diff_text, encoding="utf-8")
    return f"{safe_session}/{backup_path.name}"


def list_backups(
    workspace_root: Path,
    limit: int = 20,
    session_id: str | None = None,
) -> str:
    if limit < 1:
        raise ValueError("limit must be >= 1.")

    backups_dir = workspace_root.resolve() / ".backups"
    if not backups_dir.is_dir():
        return "No backups found."

    if session_id:
        safe_session = sanitize_session_id(session_id)
        search_root = backups_dir / safe_session
        if not search_root.is_dir():
            return f"No backups found for session '{safe_session}'."
        candidates = list(search_root.glob("*.diff"))
    else:
        candidates = list(backups_dir.rglob("*.diff"))

    if not candidates:
        return "No backups found."

    diffs = sorted(
        candidates,
        key=lambda p: (p.stat().st_mtime, p.name),
        reverse=True,
    )
    return "\n".join(p.relative_to(backups_dir).as_posix() for p in diffs[:limit])


def restore_backup(workspace_root: Path, backup_filename: str) -> str:
    if not backup_filename or not backup_filename.endswith(".diff"):
        raise ValueError(
            "backup_filename must be a '.diff' path inside .backups/ (e.g. '<session>/<file>.diff')."
        )

    cleaned = backup_filename.strip().lstrip("/")
    if cleaned.startswith(".backups/"):
        cleaned = cleaned[len(".backups/"):]

    resolved_root = workspace_root.resolve()
    backups_dir = (resolved_root / ".backups").resolve()
    if not backups_dir.is_dir():
        raise FileNotFoundError(f"Backup not found: {backup_filename}")

    backup_path = (backups_dir / cleaned).resolve()
    if not backup_path.is_relative_to(backups_dir):
        raise PermissionError("Invalid backup path.")

    # If a bare filename was provided, fall back to searching session subdirs for a unique match
    if not backup_path.is_file() and "/" not in cleaned and "\\" not in cleaned:
        matches = list(backups_dir.rglob(cleaned))
        if len(matches) == 1:
            backup_path = matches[0].resolve()
        elif len(matches) > 1:
            rel_matches = ", ".join(m.relative_to(backups_dir).as_posix() for m in matches)
            raise ValueError(
                f"Ambiguous backup filename '{backup_filename}'. Specify session path: {rel_matches}"
            )

    if not backup_path.is_file():
        raise FileNotFoundError(f"Backup not found: {backup_filename}")

    parsed = parse_unified_diff(backup_path.read_text(encoding="utf-8"))
    rel_path = parsed.relative_path
    target = (resolved_root / rel_path).resolve()
    if not target.is_relative_to(resolved_root):
        raise PermissionError(f"Backup target escapes workspace: {rel_path}")
    check_mutation_allowed(target, resolved_root)
    file_key = str(target)

    # Case 1: Reversing a brand-new file creation -> delete the file.
    if parsed.fromfile == "/dev/null":
        if target.exists():
            target.unlink()
            clear_edit_history(file_key)
            return f"Restored pre-operation state by removing newly created file '{rel_path}'."
        return f"File '{rel_path}' was already absent."

    # Case 2: Reversing a file deletion -> recreate the file from '-' lines.
    if parsed.tofile == "/dev/null":
        restored_lines: list[str] = []
        for hunk in parsed.hunks:
            restored_lines.extend(hunk.old_lines)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(restored_lines), encoding="utf-8")
        clear_edit_history(file_key)
        return f"Restored deleted file '{rel_path}' from '{backup_path.relative_to(backups_dir).as_posix()}'."

    # Case 3: Reversing an edit or overwrite -> apply hunks bottom-to-top.
    if not target.is_file():
        raise FileNotFoundError(
            f"Cannot reverse-patch '{rel_path}': file no longer exists on disk."
        )

    current_lines = target.read_text(encoding="utf-8").splitlines(keepends=True)
    for hunk in reversed(parsed.hunks):
        start_idx = hunk.new_start if hunk.new_count == 0 else hunk.new_start - 1
        end_idx = start_idx + hunk.new_count
        if current_lines[start_idx:end_idx] != hunk.new_lines:
            raise ValueError(
                f"Cannot cleanly reverse '{backup_filename}': '{rel_path}' has diverged "
                f"at line {hunk.new_start}."
            )
        current_lines[start_idx:end_idx] = hunk.old_lines

    target.write_text("".join(current_lines), encoding="utf-8")
    clear_edit_history(file_key)
    return (
        f"Restored '{rel_path}' to its pre-operation state using "
        f"'{backup_path.relative_to(backups_dir).as_posix()}'."
    )
