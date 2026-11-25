"""MCP adapter for `command_executors.read_file_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import read_file_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=True, destructive=False, idempotent=True))
    def read_file(
        path: str, start_line: int = 1, end_line: int | None = None
    ) -> str:
        """Read a UTF-8 text file with 1-indexed line numbers prefixed (e.g. `12 | def foo():`)."""
        attrs: dict[str, Any] = {"path": path, "start_line": start_line}
        if end_line is not None:
            attrs["end_line"] = end_line
        result = read_file_exec.execute(attrs, {}, ctx.to_context_state())
        return check_executor_result(result)
