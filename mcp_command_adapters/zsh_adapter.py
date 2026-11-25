"""MCP adapter for `command_executors.zsh_exec`."""

from __future__ import annotations

from typing import Any

from command_executors import zsh_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=False, destructive=True, idempotent=False))
    def zsh(command: str, timeout: int = 30) -> str:
        """Execute a command inside the workspace root (`shell=False`).

        Shell operators (`;`, `&&`, `|`, redirects, subshells) are blocked.
        Non-whitelisted commands trigger an upper-right macOS HUD approval modal.
        """
        result = zsh_exec.execute(
            {"timeout": timeout},
            {"Command": command},
            ctx.to_context_state(),
        )
        return check_executor_result(result)
