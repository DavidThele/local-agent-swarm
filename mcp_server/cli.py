"""CLI entrypoint for launching the Streamable HTTP MCP server."""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import uvicorn

from infrastructure.agent_types import AgentType
from runtime import DEFAULT_MCP_HOST, DEFAULT_MCP_PORT
from .auth import load_or_create_oauth_credentials
from .server import create_asgi_app


class _SuppressNoneSessionTerminationFilter(logging.Filter):
    """Hide noisy `Terminating session: None` logs emitted in stateless HTTP mode."""

    def filter(self, record: logging.LogRecord) -> bool:
        return record.getMessage().strip() != "Terminating session: None"


def _configure_logging() -> None:
    # Suppress `Terminating session: None` from mcp.server.streamable_http
    streamable_logger = logging.getLogger("mcp.server.streamable_http")
    streamable_logger.addFilter(_SuppressNoneSessionTerminationFilter())

    # Silence raw `"POST /mcp HTTP/1.1" 200 OK` lines; `logged_call_tool` prints concise action summaries instead
    uvicorn_access = logging.getLogger("uvicorn.access")
    uvicorn_access.handlers.clear()
    uvicorn_access.propagate = False
    uvicorn_access.disabled = True


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Expose a local directory to a remote AI agent via MCP (Streamable HTTP + OAuth 2.1)."
    )
    parser.add_argument(
        "--dir",
        type=Path,
        default=Path.cwd(),
        help="Target directory to expose (default: current working directory).",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_MCP_HOST,
        help=f"Host interface to bind to (default: {DEFAULT_MCP_HOST}).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_MCP_PORT,
        help=f"Port to listen on (default: {DEFAULT_MCP_PORT}).",
    )
    parser.add_argument(
        "--read-only",
        action="store_true",
        help="Disable file mutations, backup restoration, and zsh execution.",
    )
    parser.add_argument(
        "--session-id",
        default=None,
        help="Optional session subdirectory name inside `.backups/` (default: timestamped mcp_YYYYMMDD_HHMMSS).",
    )
    parser.add_argument(
        "--log-file",
        type=Path,
        default=None,
        help="Unified log file path for tool calls (default: <project_root>/logs/tool_calls_log.log).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    root_dir = args.dir.resolve()
    script_dir = Path(__file__).resolve().parent.parent

    creds, env_path, was_created = load_or_create_oauth_credentials(
        root_dir, script_dir
    )
    status = "Generated new" if was_created else "Loaded"
    print(
        f"[AUTH] {status} OAuth credentials ({env_path}):\n"
        f"  Client ID:     {creds.client_id}\n"
        f"  Client Secret: {creds.client_secret}",
        file=sys.stderr,
    )

    token_store_path = env_path.parent / ".oauth_tokens.json"
    app = create_asgi_app(
        root_dir,
        credentials=creds,
        read_only=args.read_only,
        session_id=args.session_id,
        log_file=args.log_file,
        token_store_path=token_store_path,
    )

    mode = "READ-ONLY" if args.read_only else "READ-WRITE"
    enabled = ", ".join(AgentType.WEB_MCP.commands)
    print(
        f"[MCP] Serving '{root_dir}' ({mode}) at http://{args.host}:{args.port}/mcp\n"
        f"[MCP] AgentType.WEB_MCP commands: {enabled}",
        file=sys.stderr,
    )
    _configure_logging()
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
