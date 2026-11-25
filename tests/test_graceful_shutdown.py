import os
import subprocess
import sys
import threading
import time
from unittest.mock import MagicMock, patch

from infrastructure import ui_bridge
from infrastructure.agent_types import AgentType
from infrastructure.concurrency import (
    cancel_all_agents,
    is_agent_active,
    register_agent,
    register_subprocess,
    terminate_all_subprocesses,
    unregister_agent,
)


def test_cancel_all_agents_unblocks_hitl_and_sets_events():
    ev_main = register_agent("shutdown_main", None, AgentType.MAIN_ORCHESTRATOR)
    ev_worker = register_agent("shutdown_worker", "shutdown_main", AgentType.WORKER)

    hitl_result: dict = {}

    def _wait_hitl():
        hitl_result["res"] = ui_bridge.request_hitl(
            agent_id="shutdown_worker",
            blocker_type="Security",
            prompt_text="Approve?",
        )

    t = threading.Thread(target=_wait_hitl, daemon=True)
    t.start()

    # Wait until the HITL blocker is registered
    deadline = time.monotonic() + 2.0
    while time.monotonic() < deadline:
        with ui_bridge._HITL_LOCK:
            if any(v.get("agent_id") == "shutdown_worker" for v in ui_bridge._PENDING_HITL.values()):
                break
        time.sleep(0.02)

    try:
        cancelled = cancel_all_agents(reason="Test shutdown")
        assert "shutdown_main" in cancelled
        assert "shutdown_worker" in cancelled
        assert ev_main.is_set()
        assert ev_worker.is_set()

        t.join(timeout=2.0)
        assert not t.is_alive()
        assert hitl_result["res"]["action"] == "cancel"
        assert "Test shutdown" in hitl_result["res"]["value"]
    finally:
        unregister_agent("shutdown_worker")
        unregister_agent("shutdown_main")
        assert not is_agent_active("shutdown_main")


def test_terminate_all_subprocesses_kills_process_group(tmp_path):
    child_pid_file = tmp_path / "child.pid"
    script = (
        "import subprocess, sys, time\n"
        f"p = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])\n"
        f"open({str(child_pid_file)!r}, 'w').write(str(p.pid))\n"
        "time.sleep(60)\n"
    )
    proc = subprocess.Popen(
        [sys.executable, "-c", script],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=(os.name == "posix"),
    )
    register_subprocess(proc)

    # Wait until child PID is written
    deadline = time.monotonic() + 5.0
    while not child_pid_file.exists() and time.monotonic() < deadline:
        time.sleep(0.05)
    assert child_pid_file.exists(), "Child subprocess did not start in time"
    child_pid = int(child_pid_file.read_text().strip())

    killed_count = terminate_all_subprocesses(grace_seconds=1.5)
    assert killed_count >= 1
    assert proc.poll() is not None

    # Verify grandchild process in the same process group was also terminated
    if os.name == "posix":
        alive = True
        for _ in range(20):
            try:
                os.kill(child_pid, 0)
                time.sleep(0.05)
            except ProcessLookupError:
                alive = False
                break
        assert not alive, f"Grandchild process {child_pid} survived process group termination"


def test_shutdown_controller_is_idempotent_and_stops_server():
    import swarm_gui

    fake_server = MagicMock()
    fake_server.should_exit = False
    fake_server.force_exit = False

    stop_flag = threading.Event()

    def _fake_server_loop():
        while not fake_server.should_exit and not stop_flag.is_set():
            time.sleep(0.02)

    server_thread = threading.Thread(target=_fake_server_loop, daemon=True)
    server_thread.start()

    ctrl = swarm_gui.SwarmShutdownController(server=fake_server, server_thread=server_thread)
    fake_window = MagicMock()
    fake_webview = MagicMock()
    fake_content_controller = MagicMock()
    fake_timer = MagicMock()
    ctrl.attach_ui(fake_window, fake_webview, fake_content_controller, signal_timer=fake_timer)

    with patch.object(swarm_gui, "_stop_appkit_run_loop") as mock_stop, \
         patch("swarm_server.shutdown_runtime") as mock_runtime_shutdown:
        ctrl.teardown_ui_and_stop_loop()
        ctrl.teardown_ui_and_stop_loop()  # Idempotent second call

        mock_stop.assert_called_once()
        fake_timer.invalidate.assert_called_once()
        fake_content_controller.removeScriptMessageHandlerForName_.assert_called_once_with("windowBridge")
        fake_webview.stopLoading.assert_called_once()
        fake_window.setDelegate_.assert_called_once_with(None)
        fake_window.orderOut_.assert_called_once_with(None)
        fake_window.setContentView_.assert_called_once_with(None)

        ctrl.cleanup_backend()
        ctrl.cleanup_backend()  # Idempotent second call

        mock_runtime_shutdown.assert_called_once()
        assert fake_server.should_exit is True
        assert not server_thread.is_alive()

    stop_flag.set()
