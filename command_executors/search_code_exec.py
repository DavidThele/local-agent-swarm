"""Plain-text and regex code search across the workspace."""

from __future__ import annotations

import fnmatch
import os
import re
from pathlib import Path

from infrastructure.workspace import IGNORED_DIRS, resolve_workspace_path
from runtime import MAX_SEARCH_RESULTS


def _parse_bool(val, default: bool = False) -> bool:
    if val is None or str(val).strip() == "":
        return default
    return str(val).strip().lower() in {"true", "1", "yes"}


def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    query = attributes.get("query")
    if not query and isinstance(content, dict):
        val = content.get("Query", "")
        query = val[0] if isinstance(val, list) else str(val)
    elif not query and isinstance(content, str):
        query = content.strip()

    if not query:
        return "[Error] SearchCode requires a 'query' attribute or <Query> tag."

    glob = attributes.get("glob") or None
    is_regex = _parse_bool(attributes.get("is_regex"), default=False)

    try:
        pattern = re.compile(query) if is_regex else None
    except re.error as exc:
        return f"[Error] Invalid regex pattern: {exc}"

    workspace_root, _ = resolve_workspace_path(".", context_state.get("workspace_root"))
    results: list[str] = []
    truncated = False

    for dirpath, dirnames, filenames in os.walk(workspace_root):
        dirnames[:] = sorted(d for d in dirnames if d not in IGNORED_DIRS)
        base = Path(dirpath)
        for fname in sorted(filenames):
            full_path = base / fname
            try:
                resolved = full_path.resolve()
            except OSError:
                continue
            if not resolved.is_relative_to(workspace_root) or not resolved.is_file():
                continue
            rel = full_path.relative_to(workspace_root)
            if any(part in IGNORED_DIRS for part in rel.parts):
                continue
            rel_posix = rel.as_posix()
            if glob and not (
                fnmatch.fnmatch(rel_posix, glob) or fnmatch.fnmatch(fname, glob)
            ):
                continue

            try:
                raw = resolved.read_bytes()
            except OSError:
                continue
            if b"\x00" in raw[:4096]:
                continue

            text = raw.decode("utf-8", errors="replace")
            for line_no, line_text in enumerate(text.splitlines(), start=1):
                matched = (
                    bool(pattern.search(line_text))
                    if pattern is not None
                    else (query in line_text)
                )
                if matched:
                    results.append(f"{rel_posix}:{line_no}: {line_text}")
                    if len(results) >= MAX_SEARCH_RESULTS:
                        truncated = True
                        break
            if truncated:
                break
        if truncated:
            break

    if not results:
        return "No matches found."
    if truncated:
        results.append(
            f"\n[Truncated at {MAX_SEARCH_RESULTS} matches. Narrow your query or glob filter.]"
        )
    return "\n".join(results)
