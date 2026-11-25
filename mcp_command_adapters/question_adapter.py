"""MCP adapter for `command_executors.question_exec` (upper-right macOS HUD modal)."""

from __future__ import annotations

from typing import Any

from command_executors import question_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(mcp, **tool_kwargs(read_only=True, destructive=False, idempotent=False))
    def question(text: str, options: list[str] | None = None) -> str:
        """Ask the user a clarifying question via an upper-right macOS HUD modal.

        Displays the question, a numbered list of clickable/Cmd+N selectable options,
        and an "Other" free-text input. Do not include an "Other" option yourself; it is
        appended automatically.
        """
        content: dict[str, Any] = {"Text": text}
        if options:
            content["Options"] = {"Option": list(options)}
        result = question_exec.execute({}, content, ctx.to_context_state())
        return check_executor_result(result)
