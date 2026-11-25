"""MCP adapter for `command_executors.edit_file_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import edit_file_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=False, destructive=False, idempotent=False))
    def edit_file(
        path: str,
        old_str: str,
        new_str: str,
        start_line: int | None = None,
        end_line: int | None = None,
        summary: str = "Applied surgical edit.",
    ) -> str:
        """Perform an exact search-and-replace edit on a file.

        Optionally scope the match to 1-indexed `start_line`..`end_line` (inclusive)
        to disambiguate repeated snippets. Automatically adjusts stale line ranges
        after prior edits to the same file and saves a unified diff to `.backups/<session>/`.
        """
        attrs: dict[str, Any] = {"path": path}
        if start_line is not None:
            attrs["start_line"] = start_line
        if end_line is not None:
            attrs["end_line"] = end_line
        result = edit_file_exec.execute(
            attrs,
            {"OldStr": old_str, "NewStr": new_str, "Summary": summary},
            ctx.to_context_state(),
        )
        return check_executor_result(result)
