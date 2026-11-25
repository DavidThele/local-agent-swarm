"""Glob-based file discovery across the workspace."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from infrastructure.workspace import IGNORED_DIRS, resolve_workspace_path
from runtime import MAX_FIND_RESULTS


def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    pattern = attributes.get("pattern")
    if not pattern and isinstance(content, dict):
        val = content.get("Pattern", "")
        pattern = val[0] if isinstance(val, list) else str(val)
    elif not pattern and isinstance(content, str):
        pattern = content.strip()

    if not pattern:
        return "[Error] FindFiles requires a 'pattern' attribute or <Pattern> tag."

    workspace_root, _ = resolve_workspace_path(".", context_state.get("workspace_root"))
    matches: list[str] = []

    for dirpath, dirnames, filenames in os.walk(workspace_root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        base = Path(dirpath)
        for fname in sorted(filenames):
            full_path = base / fname
            try:
                resolved = full_path.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(workspace_root):
                continue
            rel = full_path.relative_to(workspace_root)
            if any(part in IGNORED_DIRS for part in rel.parts):
                continue
            rel_posix = rel.as_posix()
            if fnmatch.fnmatch(rel_posix, pattern) or fnmatch.fnmatch(fname, pattern):
                matches.append(rel_posix)
                if len(matches) >= MAX_FIND_RESULTS:
                    matches.append(f"... (truncated at {MAX_FIND_RESULTS} results)")
                    return "\n".join(matches)

    return "\n".join(matches) if matches else "No files matched."
