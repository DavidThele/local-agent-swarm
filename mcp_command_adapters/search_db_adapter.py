"""MCP adapter for `command_executors.search_db_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import search_db_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=True, destructive=False, idempotent=True))
    def search_db(query: str, n_results: int = 5) -> str:
        """Search the local ChromaDB semantic memory database for relevant chunks."""
        result = search_db_exec.execute(
            {"n_results": n_results},
            {"Query": query},
            ctx.to_context_state(),
        )
        return check_executor_result(result)
