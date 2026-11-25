"""MCP adapter for `command_executors.find_files_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import find_files_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=True, destructive=False, idempotent=True))
    def find_files(pattern: str) -> str:
        """Find files across the workspace matching a glob pattern (e.g. '*.py', 'src/**/*.ts')."""
        result = find_files_exec.execute(
            {"pattern": pattern},
            {},
            ctx.to_context_state(),
        )
        return check_executor_result(result)
