"""Tests for merged MCP server, session-organized backups, command executors, and HUD modal queuing."""

from __future__ import annotations

import asyncio
import json
import socket
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from command_executors import (
    delete_file_exec,
    edit_file_exec,
    find_files_exec,
    list_backups_exec,
    list_directory_exec,
    question_exec,
    read_file_exec,
    restore_backup_exec,
    search_code_exec,
    write_file_exec,
)
from infrastructure import ui_bridge
from infrastructure.agent_types import AgentType
from mcp_command_adapters import ADAPTER_REGISTRY, MUTATING_COMMANDS
from mcp_server.server import create_mcp_server

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_agent_types_commands_and_docs_exist():
    assert AgentType.WEB_MCP.value == "web_mcp"
    for role in AgentType:
        for cmd in role.commands:
            assert (REPO_ROOT / "commands" / f"{cmd}.md").is_file(), f"Missing commands/{cmd}.md"
            assert (REPO_ROOT / "command_executors" / f"{cmd}_exec.py").is_file(), (
                f"Missing command_executors/{cmd}_exec.py"
            )

    for cmd in AgentType.WEB_MCP.commands:
        assert cmd in ADAPTER_REGISTRY, f"Missing MCP adapter for WEB_MCP command '{cmd}'"

    # Verify requested role grants
    for shared in ("find_files", "search_code", "list_backups", "restore_backup"):
        assert shared in AgentType.MAIN_ORCHESTRATOR.commands
        assert shared in AgentType.SUB_ORCHESTRATOR.commands
        assert shared in AgentType.WORKER.commands

    for worker_only in ("edit_file", "delete_file"):
        assert worker_only in AgentType.WORKER.commands
        assert worker_only not in AgentType.MAIN_ORCHESTRATOR.commands
        assert worker_only not in AgentType.SUB_ORCHESTRATOR.commands


def test_session_backups_gitignore_and_edit_shift_projection(tmp_path: Path):
    (tmp_path / ".gitignore").write_text("ignored_dir/\n*.tmp\n", encoding="utf-8")
    ctx = {"workspace_root": str(tmp_path), "session_id": "test_session_1", "worker_id": "w1"}

    # 1. Write a tracked file -> backup created under .backups/test_session_1/
    res = write_file_exec.execute(
        {"path": "app.py"},
        {"Content": "line1\nline2\nfoo = 1\nline4\nbar = 1\n", "Summary": "init"},
        ctx,
    )
    assert "[Success]" in res
    assert ".backups/test_session_1/" in res

    # 2. Write a gitignored file -> succeeds, NO backup created
    res_ign = write_file_exec.execute(
        {"path": "scratch.tmp"},
        {"Content": "temp", "Summary": "temp"},
        ctx,
    )
    assert "[Success]" in res_ign
    assert "Backup saved:" not in res_ign

    # 3. Surgical edit_file with stale line-range shift projection
    # First edit inserts 2 extra lines at top (lines 1-2)
    e1 = edit_file_exec.execute(
        {"path": "app.py", "start_line": 1, "end_line": 2},
        {"OldStr": "line1\n", "NewStr": "line1\nextraA\nextraB\n"},
        ctx,
    )
    assert "line delta: +2" in e1

    # Second edit targets original line 5 ("bar = 1"), now shifted to line 7
    e2 = edit_file_exec.execute(
        {"path": "app.py", "start_line": 5, "end_line": 5},
        {"OldStr": "bar = 1", "NewStr": "bar = 2"},
        ctx,
    )
    assert "adjusted from" in e2
    assert (tmp_path / "app.py").read_text(encoding="utf-8").endswith("bar = 2\n")

    # 4. List backups and restore the last edit
    listed = list_backups_exec.execute({"limit": 10, "session_id": "test_session_1"}, {}, ctx)
    backup_lines = [ln for ln in listed.splitlines() if ln.strip()]
    assert len(backup_lines) == 3  # write + 2 edits (scratch.tmp excluded)
    assert all(ln.startswith("test_session_1/") for ln in backup_lines)

    latest_backup = backup_lines[0]
    restored = restore_backup_exec.execute({"backup_filename": latest_backup}, {}, ctx)
    assert "Restored 'app.py'" in restored
    assert (tmp_path / "app.py").read_text(encoding="utf-8").endswith("bar = 1\n")

    # 5. Delete file and restore it
    del_res = delete_file_exec.execute({"path": "app.py"}, {}, ctx)
    assert "Deleted 'app.py'" in del_res
    assert not (tmp_path / "app.py").exists()

    listed_after_del = list_backups_exec.execute({"limit": 1, "session_id": "test_session_1"}, {}, ctx)
    restore_del = restore_backup_exec.execute({"backup_filename": listed_after_del.strip()}, {}, ctx)
    assert "Restored deleted file 'app.py'" in restore_del
    assert (tmp_path / "app.py").exists()


def test_find_files_and_search_code(tmp_path: Path):
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "alpha.py").write_text("def hello_world():\n    return 42\n", encoding="utf-8")
    (tmp_path / "src" / "beta.txt").write_text("hello text\n", encoding="utf-8")
    ctx = {"workspace_root": str(tmp_path)}

    found = find_files_exec.execute({"pattern": "*.py"}, {}, ctx)
    assert found.strip() == "src/alpha.py"

    hits = search_code_exec.execute({"query": "hello_world", "glob": "*.py"}, {}, ctx)
    assert "src/alpha.py:1: def hello_world():" in hits

    tree = list_directory_exec.execute({"path": ".", "depth": 2}, {}, ctx)
    assert "alpha.py" in tree


def test_mcp_server_respects_permissions_and_read_only(tmp_path: Path):
    log_file = tmp_path / "tool_calls.log"
    mcp_rw = create_mcp_server(tmp_path, read_only=False, log_file=log_file)
    tools_rw = asyncio.run(mcp_rw.list_tools())
    names_rw = {t.name for t in tools_rw}
    assert set(AgentType.WEB_MCP.commands) == names_rw

    mcp_ro = create_mcp_server(tmp_path, read_only=True, log_file=log_file)
    tools_ro = asyncio.run(mcp_ro.list_tools())
    names_ro = {t.name for t in tools_ro}
    assert names_ro.isdisjoint(MUTATING_COMMANDS)
    assert "read_file" in names_ro
    assert "list_directory" in names_ro
    assert "question" in names_ro

    # Custom subset via allowed_commands
    mcp_custom = create_mcp_server(
        tmp_path, allowed_commands=("read_file", "list_directory"), log_file=log_file
    )
    names_custom = {t.name for t in asyncio.run(mcp_custom.list_tools())}
    assert names_custom == {"read_file", "list_directory"}


def test_resident_modal_queue_serializes_and_batches_replies():
    import os
    from macro_synth.macro_service import MacroService

    sock_path = Path(f"/tmp/test_hud_{os.getpid()}.sock")
    order: list[str] = []

    class FakeModal:
        def prompt_sync(self, payload: dict) -> dict:
            order.append(payload["prompt_text"])
            time.sleep(0.05)
            return {"action": "answer", "value": f"ans:{payload['prompt_text']}"}

        def cancel_if_active(self, blocker_id=None, reason="cancelled_externally"):
            return False

    service = MacroService(hud=None, hitl_modal=FakeModal())  # type: ignore[arg-type]

    with patch("macro_synth.macro_service.SOCKET_PATH", sock_path):
        service.start()
        try:
            # Wait briefly for socket bind
            for _ in range(30):
                if sock_path.exists():
                    break
                time.sleep(0.02)

            results: dict[str, tuple[float, dict]] = {}

            def send_q(label: str):
                with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as c:
                    c.connect(str(sock_path))
                    req = {
                        "type": "hitl_modal",
                        "blocker_id": f"blk_{label}",
                        "blocker_type": "Question",
                        "prompt_text": label,
                        "options": ["A", "B"],
                    }
                    c.sendall((json.dumps(req) + "\n").encode("utf-8"))
                    data = c.recv(4096).decode("utf-8").strip()
                    results[label] = (time.monotonic(), json.loads(data))

            t1 = threading.Thread(target=send_q, args=("Q1",))
            t2 = threading.Thread(target=send_q, args=("Q2",))
            t1.start()
            time.sleep(0.01)
            t2.start()
            t1.join(timeout=5)
            t2.join(timeout=5)

            assert len(order) == 2
            assert set(results.keys()) == {"Q1", "Q2"}
            assert results["Q1"][1]["value"] == "ans:Q1"
            assert results["Q2"][1]["value"] == "ans:Q2"
            # Both replies are released together once the queue drains
            assert abs(results["Q1"][0] - results["Q2"][0]) < 0.1
        finally:
            service.stop_event.set()
            if service.server_thread:
                service.server_thread.join(timeout=2)


def test_ui_bridge_and_hud_modal_bidirectional_sync():
    events: list[dict] = []
    loop = asyncio.new_event_loop()

    async def fake_broadcast(msg: dict):
        events.append(msg)

    ui_bridge.register_bridge(loop, fake_broadcast)
    try:
        def fake_hud_request(**kwargs):
            time.sleep(0.05)
            return {"action": "answer", "value": "from_hud"}

        with (
            patch("infrastructure.hud_client.is_hud_modal_disabled", return_value=False),
            patch("infrastructure.hud_client.request_hitl_modal", side_effect=fake_hud_request),
            patch("infrastructure.hud_client.cancel_hitl_modal") as mock_cancel,
        ):
            res = ui_bridge.request_hitl(
                agent_id="main",
                blocker_type="Question",
                prompt_text="Pick one",
                options=["Opt1"],
            )
            assert res == {"action": "answer", "value": "from_hud"}
            # Resolved from HUD, so cancel_hitl_modal should NOT be called
            mock_cancel.assert_not_called()
    finally:
        ui_bridge.unregister_bridge()
        loop.close()
