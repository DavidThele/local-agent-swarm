"""MCP adapter for `command_executors.delete_file_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import delete_file_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=False, destructive=True, idempotent=False))
    def delete_file(path: str) -> str:
        """Delete a file after saving its full-content unified diff to `.backups/<session>/`."""
        result = delete_file_exec.execute(
            {"path": path},
            {},
            ctx.to_context_state(),
        )
        return check_executor_result(result)
