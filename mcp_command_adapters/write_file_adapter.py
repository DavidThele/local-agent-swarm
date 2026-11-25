"""MCP adapter for `command_executors.write_file_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import write_file_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=False, destructive=True, idempotent=True))
    def write_file(path: str, content: str, summary: str = "Overwrote file.") -> str:
        """Create a new file (and parent dirs if needed) or overwrite an existing file.

        Automatically logs a unified diff to `.backups/<session>/` before writing (excluding .gitignore matches).
        """
        result = write_file_exec.execute(
            {"path": path},
            {"Content": content, "Summary": summary},
            ctx.to_context_state(),
        )
        return check_executor_result(result)
