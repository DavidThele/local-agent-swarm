"""MCP adapter for `command_executors.restore_backup_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import restore_backup_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=False, destructive=False, idempotent=False))
    def restore_backup(backup_filename: str) -> str:
        """Reverse a `.diff` file in `.backups/<session>/` to restore the target file to its pre-operation state."""
        result = restore_backup_exec.execute(
            {"backup_filename": backup_filename},
            {},
            ctx.to_context_state(),
        )
        return check_executor_result(result)
