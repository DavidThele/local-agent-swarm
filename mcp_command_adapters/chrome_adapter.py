"""MCP adapter for `command_executors.chrome_exec` (returns DOM text + screenshot image when available)."""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

try:
    from mcp.types import ImageContent, TextContent
except ImportError:
    ImageContent = None  # type: ignore[assignment,misc]
    TextContent = None  # type: ignore[assignment,misc]

from command_executors import chrome_exec
from ._common import MCPContext, check_executor_result, register_tool, tool_kwargs


def register(mcp: Any, ctx: MCPContext) -> None:
    @register_tool(
        mcp,
        **tool_kwargs(read_only=False, destructive=False, idempotent=False, open_world=True),
    )
    def chrome(
        action: str,
        url: str | None = None,
        target_id: str | None = None,
        text: str | None = None,
        direction: str = "down",
    ) -> Any:
        """Control the local Chrome browser over CDP (`navigate`, `click`, `type`, `scroll`, `close`).

        Returns the labeled interactive DOM elements and, when available, a PNG screenshot.
        """
        attrs: dict[str, Any] = {"action": action, "direction": direction}
        if url is not None:
            attrs["url"] = url
        if target_id is not None:
            attrs["target_id"] = target_id

        content: dict[str, Any] = {"Text": text} if text is not None else {}
        state = ctx.to_context_state()
        result = chrome_exec.execute(attrs, content, state)
        checked = check_executor_result(result)

        screenshot_path_str = state.get("last_chrome_screenshot")
        if (
            screenshot_path_str
            and ImageContent is not None
            and TextContent is not None
        ):
            screenshot_path = Path(screenshot_path_str)
            if screenshot_path.is_file():
                try:
                    encoded = base64.b64encode(screenshot_path.read_bytes()).decode("ascii")
                    return [
                        TextContent(type="text", text=checked),
                        ImageContent(type="image", data=encoded, mime_type="image/png"),
                    ]
                except OSError:
                    pass

        return checked
