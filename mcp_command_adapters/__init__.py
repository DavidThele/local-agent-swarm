"""Registry of MCP command adapters backed by `command_executors/*_exec.py`."""

from __future__ import annotations

from typing import Any, Callable, Iterable

from infrastructure.logging import log
from ._common import MCPContext
from . import (
    chrome_adapter,
    delete_file_adapter,
    edit_file_adapter,
    find_files_adapter,
    list_backups_adapter,
    list_directory_adapter,
    question_adapter,
    read_file_adapter,
    restore_backup_adapter,
    search_code_adapter,
    search_db_adapter,
    write_file_adapter,
    zsh_adapter,
)

AdapterRegisterFn = Callable[[Any, MCPContext], None]

ADAPTER_REGISTRY: dict[str, AdapterRegisterFn] = {
    "list_directory": list_directory_adapter.register,
    "find_files": find_files_adapter.register,
    "search_code": search_code_adapter.register,
    "read_file": read_file_adapter.register,
    "write_file": write_file_adapter.register,
    "edit_file": edit_file_adapter.register,
    "delete_file": delete_file_adapter.register,
    "list_backups": list_backups_adapter.register,
    "restore_backup": restore_backup_adapter.register,
    "zsh": zsh_adapter.register,
    "search_db": search_db_adapter.register,
    "chrome": chrome_adapter.register,
    "question": question_adapter.register,
}

MUTATING_COMMANDS: frozenset[str] = frozenset(
    {
        "write_file",
        "edit_file",
        "delete_file",
        "restore_backup",
        "zsh",
    }
)


def register_allowed_commands(
    mcp: Any,
    ctx: MCPContext,
    commands: Iterable[str],
) -> list[str]:
    """Register every allowed command that has an adapter (respecting `ctx.read_only`)."""
    registered: list[str] = []
    for cmd_name in commands:
        if ctx.read_only and cmd_name in MUTATING_COMMANDS:
            continue
        register_fn = ADAPTER_REGISTRY.get(cmd_name)
        if register_fn is None:
            log(f"[MCP] No MCP adapter registered for command '{cmd_name}'; skipping.", "warning")
            continue
        register_fn(mcp, ctx)
        registered.append(cmd_name)
    return registered


__all__ = [
    "ADAPTER_REGISTRY",
    "MCPContext",
    "MUTATING_COMMANDS",
    "register_allowed_commands",
]
