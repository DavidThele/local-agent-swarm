"""MCP adapter for `command_executors.list_directory_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import list_directory_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=True, destructive=False, idempotent=True))
    def list_directory(path: str = ".", depth: int = 3) -> str:
        """List files and directories as an indented tree with file size and line-count metadata.

        Ignores .backups/, .git/, node_modules/, .venv/, __pycache__/, dist/, build/, etc.
        """
        result = list_directory_exec.execute(
            {"path": path, "depth": depth},
            {},
            ctx.to_context_state(),
        )
        return check_executor_result(result)
