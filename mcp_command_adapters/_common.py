"""Shared helpers and context for MCP command adapters."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from pathlib import Path
from typing import Any

try:
    from mcp.server.mcpserver.exceptions import ToolError
except ImportError:
    ToolError = None  # type: ignore[assignment,misc]

try:
    from mcp.types import CallToolResult, TextContent, ToolAnnotations
except ImportError:
    CallToolResult = None  # type: ignore[assignment,misc]
    TextContent = None  # type: ignore[assignment,misc]
    ToolAnnotations = None  # type: ignore[assignment,misc]

_EXPECTED_TOOL_ERRORS = (
    ValueError,
    PermissionError,
    FileNotFoundError,
    IsADirectoryError,
    NotADirectoryError,
)


@dataclass
class MCPContext:
    workspace_root: Path
    session_id: str
    read_only: bool = False
    worker_id: str = "web_mcp"
    local_chat_dir: Path | None = None

    def to_context_state(self) -> dict[str, Any]:
        state: dict[str, Any] = {
            "workspace_root": str(self.workspace_root.resolve()),
            "session_id": self.session_id,
            "worker_id": self.worker_id,
        }
        if self.local_chat_dir is not None:
            state["local_chat_dir"] = str(self.local_chat_dir)
        else:
            state["local_chat_dir"] = str(self.workspace_root / ".agents" / "chats" / self.session_id)
        return state


def tool_kwargs(
    *,
    read_only: bool,
    destructive: bool,
    idempotent: bool,
    open_world: bool = False,
) -> dict[str, Any]:
    if ToolAnnotations is None:
        return {}
    return {
        "annotations": ToolAnnotations(
            read_only_hint=read_only,
            destructive_hint=destructive,
            idempotent_hint=idempotent,
            open_world_hint=open_world,
        )
    }


def surface_tool_errors(fn: Any) -> Any:
    @functools.wraps(fn)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        try:
            return fn(*args, **kwargs)
        except _EXPECTED_TOOL_ERRORS as exc:
            if ToolError is not None:
                raise ToolError(str(exc)) from exc
            if CallToolResult is not None and TextContent is not None:
                return CallToolResult(
                    content=[TextContent(type="text", text=str(exc))],
                    is_error=True,
                )
            raise

    return wrapper


def register_tool(mcp: Any, **kwargs: Any) -> Any:
    def decorator(fn: Any) -> Any:
        return mcp.tool(**kwargs)(surface_tool_errors(fn))

    return decorator


def check_executor_result(result: str) -> str:
    """Convert `[Error]` / `[FILE_ACCESS_DENIED]` executor outputs into MCP tool errors."""
    if isinstance(result, str):
        if result.startswith("[FILE_ACCESS_DENIED]"):
            raise PermissionError(result)
        if result.startswith("[Error]"):
            raise ValueError(result)
    return result
