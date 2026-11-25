"""MCP adapter for `command_executors.list_backups_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import list_backups_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=True, destructive=False, idempotent=True))
    def list_backups(limit: int = 20, session_id: str | None = None) -> str:
        """List recent unified `.diff` backup files in `.backups/<session>/`, sorted newest-first."""
        attrs: dict[str, Any] = {"limit": limit}
        if session_id is not None:
            attrs["session_id"] = session_id
        result = list_backups_exec.execute(attrs, {}, ctx.to_context_state())
        return check_executor_result(result)
