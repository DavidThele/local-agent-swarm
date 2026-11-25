"""Unified logging for MCP tool calls into a single log file."""

from __future__ import annotations

import json
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from runtime import DEFAULT_MCP_CALL_LOG_PATH as DEFAULT_CALL_LOG_PATH, REPO_ROOT as DEFAULT_PROJECT_ROOT

_WRITE_LOCK = threading.Lock()


def _safe_json_args(arguments: dict[str, Any] | None) -> str:
    if not arguments:
        return "{}"
    try:
        return json.dumps(arguments, default=str, ensure_ascii=False, separators=(",", ":"))
    except Exception:
        return repr(arguments)


class ToolCallLogger:
    """Thread-safe line logger that appends every tool call to a unified log file."""

    def __init__(self, log_file: Path | None = None) -> None:
        self.log_file = (log_file or DEFAULT_CALL_LOG_PATH).resolve()

    def record(
        self,
        tool_name: str,
        arguments: dict[str, Any] | None,
        *,
        status: str,
        duration_ms: float,
        error: str | None = None,
    ) -> None:
        timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")
        args_str = _safe_json_args(arguments)
        line = (
            f"{timestamp} | status={status} | duration={duration_ms:.1f}ms "
            f"| tool={tool_name} | args={args_str}"
        )
        if error:
            clean_err = " ".join(error.splitlines()).strip()
            line = f"{line} | error={clean_err!r}"
        line = f"{line}\n"

        with _WRITE_LOCK:
            self.log_file.parent.mkdir(parents=True, exist_ok=True)
            with self.log_file.open("a", encoding="utf-8") as fh:
                fh.write(line)
                fh.flush()

    def start_timer(self) -> float:
        return time.perf_counter()

    def elapsed_ms(self, start: float) -> float:
        return (time.perf_counter() - start) * 1000.0
