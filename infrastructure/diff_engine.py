"""Unified diff generation and reverse-patch parsing for `.backups/`."""

from __future__ import annotations

import difflib
import re
from dataclasses import dataclass

_HUNK_HEADER_RE = re.compile(
    r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@"
)


@dataclass(frozen=True)
class DiffHunk:
    old_start: int
    old_count: int
    new_start: int
    new_count: int
    old_lines: list[str]
    new_lines: list[str]


@dataclass(frozen=True)
class ParsedDiff:
    fromfile: str
    tofile: str
    hunks: list[DiffHunk]

    @property
    def relative_path(self) -> str:
        if self.fromfile != "/dev/null":
            return self.fromfile[2:] if self.fromfile.startswith("a/") else self.fromfile
        return self.tofile[2:] if self.tofile.startswith("b/") else self.tofile


def generate_unified_diff(
    old_content: str,
    new_content: str,
    rel_path: str,
    *,
    is_new_file: bool = False,
    is_delete: bool = False,
) -> str:
    """Generate a standard unified diff preserving trailing-newline semantics."""
    old_lines = old_content.splitlines(keepends=True) if old_content else []
    new_lines = new_content.splitlines(keepends=True) if new_content else []

    fromfile = "/dev/null" if is_new_file else f"a/{rel_path}"
    tofile = "/dev/null" if is_delete else f"b/{rel_path}"

    raw_diff = list(
        difflib.unified_diff(
            old_lines,
            new_lines,
            fromfile=fromfile,
            tofile=tofile,
            lineterm="\n",
        )
    )

    formatted: list[str] = []
    for line in raw_diff:
        if line.endswith("\n"):
            formatted.append(line)
        else:
            formatted.append(line + "\n")
            formatted.append("\\ No newline at end of file\n")
    return "".join(formatted)


def _strip_last_newline(lines: list[str]) -> None:
    if lines and lines[-1].endswith("\n"):
        lines[-1] = lines[-1][:-1]


def parse_unified_diff(diff_text: str) -> ParsedDiff:
    """Parse a unified diff into file headers and structured hunks."""
    lines = diff_text.splitlines(keepends=True)
    fromfile = ""
    tofile = ""
    hunks: list[DiffHunk] = []

    idx = 0
    while idx < len(lines):
        line = lines[idx]
        if line.startswith("--- "):
            fromfile = line[4:].strip()
            idx += 1
        elif line.startswith("+++ "):
            tofile = line[4:].strip()
            idx += 1
        elif line.startswith("@@ "):
            match = _HUNK_HEADER_RE.match(line)
            if not match:
                raise ValueError(f"Malformed hunk header: {line.strip()!r}")
            old_start = int(match.group(1))
            old_count = int(match.group(2)) if match.group(2) is not None else 1
            new_start = int(match.group(3))
            new_count = int(match.group(4)) if match.group(4) is not None else 1

            old_hunk: list[str] = []
            new_hunk: list[str] = []
            last_tag: str | None = None
            idx += 1

            while idx < len(lines):
                hline = lines[idx]
                if hline.startswith("@@ ") or hline.startswith("--- "):
                    break
                if hline.startswith("\\ No newline at end of file"):
                    if last_tag == "-":
                        _strip_last_newline(old_hunk)
                    elif last_tag == "+":
                        _strip_last_newline(new_hunk)
                    elif last_tag == " ":
                        _strip_last_newline(old_hunk)
                        _strip_last_newline(new_hunk)
                elif hline.startswith("-"):
                    old_hunk.append(hline[1:])
                    last_tag = "-"
                elif hline.startswith("+"):
                    new_hunk.append(hline[1:])
                    last_tag = "+"
                elif hline.startswith(" "):
                    old_hunk.append(hline[1:])
                    new_hunk.append(hline[1:])
                    last_tag = " "
                else:
                    raise ValueError(f"Unexpected diff line: {hline!r}")
                idx += 1

            hunks.append(
                DiffHunk(
                    old_start=old_start,
                    old_count=old_count,
                    new_start=new_start,
                    new_count=new_count,
                    old_lines=old_hunk,
                    new_lines=new_hunk,
                )
            )
        else:
            idx += 1

    if not fromfile or not tofile:
        raise ValueError("Invalid unified diff: missing '---' or '+++' file headers.")

    return ParsedDiff(fromfile=fromfile, tofile=tofile, hunks=hunks)
