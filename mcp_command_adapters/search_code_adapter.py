"""MCP adapter for `command_executors.search_code_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import search_code_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=True, destructive=False, idempotent=True))
    def search_code(
        query: str, glob: str | None = None, is_regex: bool = False
    ) -> str:
        """Search text files in the workspace for `query` (plain string or regex).

        Returns `path:line_number: line_text` entries, capped to protect context size.
        Optionally filter files with `glob` (e.g. '*.py').
        """
        attrs: dict[str, Any] = {"query": query, "is_regex": is_regex}
        if glob is not None:
            attrs["glob"] = glob
        result = search_code_exec.execute(attrs, {}, ctx.to_context_state())
        return check_executor_result(result)
