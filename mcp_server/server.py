"""FastMCP / MCPServer tool registration and Streamable HTTP ASGI app factory."""

from __future__ import annotations

import functools
import inspect
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from starlette.types import ASGIApp

from infrastructure.agent_types import AgentType
from infrastructure.backups import sanitize_session_id
from mcp_command_adapters import MCPContext, register_allowed_commands
from .auth import OAuthCredentials, OAuthMiddleware
from .call_logger import ToolCallLogger

try:
    from mcp.server import MCPServer as _ServerClass  # type: ignore[attr-defined]
except ImportError:
    from mcp.server.mcpserver import MCPServer as _ServerClass

try:
    from mcp.server.transport_security import TransportSecuritySettings
except ImportError:
    TransportSecuritySettings = None  # type: ignore[assignment,misc]


def _default_mcp_session_id() -> str:
    return f"mcp_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}"


def _summarize_tool_call(tool_name: str, args: dict[str, Any]) -> str:
    """Produce a concise, human-readable summary of an MCP tool call for terminal logs."""
    def _clip(val: Any, max_len: int = 80) -> str:
        s = " ".join(str(val).splitlines()).strip()
        return s if len(s) <= max_len else s[: max_len - 3] + "..."

    if tool_name == "zsh":
        return f"zsh: {_clip(args.get('command', ''))}"
    if tool_name == "write_file":
        return f"write_file: {args.get('path', '')}"
    if tool_name == "edit_file":
        path = args.get("path", "")
        s, e = args.get("start_line"), args.get("end_line")
        loc = f" (L{s}-{e})" if s is not None or e is not None else ""
        return f"edit_file: {path}{loc}"
    if tool_name == "delete_file":
        return f"delete_file: {args.get('path', '')}"
    if tool_name == "read_file":
        path = args.get("path", "")
        s, e = args.get("start_line"), args.get("end_line")
        loc = f" (L{s}-{e})" if (s and s != 1) or e is not None else ""
        return f"read_file: {path}{loc}"
    if tool_name == "list_directory":
        return f"list_directory: {args.get('path', '.')} (depth={args.get('depth', 3)})"
    if tool_name == "find_files":
        return f"find_files: {args.get('pattern', '')}"
    if tool_name == "search_code":
        glob = f" [{args['glob']}]" if args.get("glob") else ""
        return f"search_code: {_clip(args.get('query', ''), 60)}{glob}"
    if tool_name == "search_db":
        return f"search_db: {_clip(args.get('query', ''), 70)}"
    if tool_name == "list_backups":
        sess = f" (session={args['session_id']})" if args.get("session_id") else ""
        return f"list_backups (limit={args.get('limit', 20)}){sess}"
    if tool_name == "restore_backup":
        return f"restore_backup: {args.get('backup_filename', '')}"
    if tool_name == "chrome":
        action = args.get("action", "")
        target = args.get("url") or args.get("target_id") or args.get("direction") or ""
        return f"chrome {action}: {_clip(target, 60)}".rstrip(": ")
    if tool_name == "question":
        return f"question: {_clip(args.get('text', ''), 70)}"

    compact = ", ".join(f"{k}={_clip(v, 30)}" for k, v in args.items())
    return f"{tool_name}({compact})" if compact else tool_name


def create_mcp_server(
    workspace_root: Path,
    *,
    read_only: bool = False,
    allowed_commands: Iterable[str] | None = None,
    session_id: str | None = None,
    log_file: Path | None = None,
) -> Any:
    """Create and configure the MCP server using `AgentType.WEB_MCP.commands` and `mcp_command_adapters`."""
    resolved_root = workspace_root.resolve()
    if not resolved_root.is_dir():
        raise ValueError(f"Target directory does not exist: {resolved_root}")

    call_logger = ToolCallLogger(log_file=log_file)
    resolved_session = sanitize_session_id(session_id or _default_mcp_session_id())
    commands_to_enable = (
        tuple(allowed_commands)
        if allowed_commands is not None
        else AgentType.WEB_MCP.commands
    )

    server_kwargs: dict[str, Any] = {
        "instructions": (
            "You are connected to a local workspace over Streamable HTTP MCP. "
            "Use list_directory, find_files, search_code, and read_file to inspect code. "
            "Prefer edit_file over write_file for targeted changes. Every tracked mutation "
            "automatically saves a unified diff to .backups/<session>/ that can be reverted with restore_backup."
        ),
    }
    init_sig = inspect.signature(_ServerClass.__init__)
    if "stateless_http" in init_sig.parameters:
        server_kwargs["stateless_http"] = True

    mcp = _ServerClass("local-code-workspace", **server_kwargs)
    ctx = MCPContext(
        workspace_root=resolved_root,
        session_id=resolved_session,
        read_only=read_only,
    )
    register_allowed_commands(mcp, ctx, commands_to_enable)

    original_call_tool = mcp.call_tool

    @functools.wraps(original_call_tool)
    async def logged_call_tool(
        name: str,
        arguments: dict[str, Any] | None = None,
        context: Any = None,
    ) -> Any:
        args_dict = arguments or {}
        summary = _summarize_tool_call(name, args_dict)
        started = call_logger.start_timer()
        try:
            result = await original_call_tool(name, args_dict, context)
        except Exception as exc:
            detail = str(exc.__cause__ or exc)
            dur = call_logger.elapsed_ms(started)
            print(f"[MCP] {summary} -> ERROR ({dur:.0f}ms): {detail}", flush=True)
            call_logger.record(
                name,
                args_dict,
                status="error",
                duration_ms=dur,
                error=detail,
            )
            raise

        is_err = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
        err_text: str | None = None
        dur = call_logger.elapsed_ms(started)
        if is_err:
            content = getattr(result, "content", None) or []
            parts = [getattr(item, "text", "") for item in content if getattr(item, "text", "")]
            err_text = " ".join(parts) if parts else "Tool returned error result"
            print(f"[MCP] {summary} -> ERROR ({dur:.0f}ms): {err_text}", flush=True)
        else:
            print(f"[MCP] {summary} ({dur:.0f}ms)", flush=True)

        call_logger.record(
            name,
            args_dict,
            status="error" if is_err else "ok",
            duration_ms=dur,
            error=err_text,
        )
        return result

    mcp.call_tool = logged_call_tool
    return mcp


def create_asgi_app(
    workspace_root: Path,
    credentials: OAuthCredentials,
    *,
    read_only: bool = False,
    allowed_commands: Iterable[str] | None = None,
    session_id: str | None = None,
    log_file: Path | None = None,
    token_store_path: Path | None = None,
) -> ASGIApp:
    """Build the Streamable HTTP ASGI app wrapped with OAuth 2.1 authentication."""
    resolved_root = workspace_root.resolve()
    mcp = create_mcp_server(
        resolved_root,
        read_only=read_only,
        allowed_commands=allowed_commands,
        session_id=session_id,
        log_file=log_file,
    )
    app_kwargs: dict[str, Any] = {}

    sig = inspect.signature(mcp.streamable_http_app)
    if "stateless_http" in sig.parameters:
        app_kwargs["stateless_http"] = True
    if TransportSecuritySettings is not None and "transport_security" in sig.parameters:
        app_kwargs["transport_security"] = TransportSecuritySettings(
            enable_dns_rebinding_protection=False
        )

    starlette_app = mcp.streamable_http_app(**app_kwargs)
    resolved_store = token_store_path or (resolved_root / ".oauth_tokens.json")
    return OAuthMiddleware(
        starlette_app,
        credentials=credentials,
        token_store_path=resolved_store,
    )
