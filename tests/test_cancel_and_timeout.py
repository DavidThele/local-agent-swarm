import queue
import threading
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from infrastructure import agent_loop
from infrastructure.agent_types import AgentType
from infrastructure.concurrency import cancel_agent_tree, is_agent_active


def _make_state(tmp_path: Path, thinking_timeout: float | None = None) -> dict:
    state = {
        "local_chat_dir": str(tmp_path / "chat"),
        "workspace_root": str(tmp_path),
        "worker_id": "main",
        "parent_agent_id": None,
        "notification_queue": queue.Queue(),
        "active_children": {},
    }
    if thinking_timeout is not None:
        state["thinking_timeout_seconds"] = thinking_timeout
    return state


def test_cancel_worker_reports_error_to_parent(tmp_path):
    """Cancelling a worker fails that worker and delivers the error notification to the parent orchestrator."""
    worker_started = threading.Event()
    parent_saw_error = {}

    def fake_send_prompt(prompt_text, model, chat_history=None, google_search=False, cancel_event=None):
        chat_history = chat_history or []
        if "DO_WORKER_TASK" in prompt_text:
            worker_started.set()
            # Simulate a long thinking call that blocks until cancelled
            for _ in range(100):
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("cancelled")
                time.sleep(0.05)
            return "<MarkDone>done</MarkDone>", chat_history, {"total_cost": 0.0}

        if "[Completed Child Agent Notifications]" in prompt_text:
            parent_saw_error["prompt"] = prompt_text
            return "<MarkDone>Handled worker failure</MarkDone>", chat_history, {"total_cost": 0.0}

        return (
            '<SpawnAgent type="worker"><Instructions>DO_WORKER_TASK</Instructions><Context>c</Context><DoD>d</DoD></SpawnAgent>'
            '<WaitForAgents mode="all" />',
            chat_history,
            {"total_cost": 0.0},
        )

    state = _make_state(tmp_path)

    def _cancel_worker_once_running():
        assert worker_started.wait(timeout=5)
        # Find active worker id from parent's active_children
        for _ in range(50):
            if state["active_children"]:
                break
            time.sleep(0.02)
        worker_id = next(iter(state["active_children"].keys()))
        cancelled = cancel_agent_tree(worker_id, reason="Stopped from UI")
        assert cancelled == [worker_id]

    canceller = threading.Thread(target=_cancel_worker_once_running, daemon=True)
    canceller.start()

    with patch.object(agent_loop, "send_prompt", side_effect=fake_send_prompt), \
         patch.object(agent_loop, "load_prompt", return_value="SYS"):
        res = agent_loop.run_agent(
            agent_type=AgentType.MAIN_ORCHESTRATOR,
            instructions="Run a worker",
            context="",
            dod="Handle result",
            chat_context_state=state,
            agent_id="main",
        )

    canceller.join(timeout=5)
    assert res["status"] == "success"
    assert "STATUS: FAILED" in parent_saw_error["prompt"]
    assert "Stopped from UI" in parent_saw_error["prompt"]


def test_cancel_sub_orchestrator_cascades_to_workers(tmp_path):
    """Cancelling a sub-orchestrator cancels both the sub-orchestrator and all workers spawned off it."""
    worker_started = threading.Event()
    sub_id_holder = {}
    worker_id_holder = {}
    main_saw = {}

    def fake_send_prompt(prompt_text, model, chat_history=None, google_search=False, cancel_event=None):
        chat_history = chat_history or []
        if "LEAF_WORKER" in prompt_text:
            worker_started.set()
            for _ in range(100):
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("cancelled")
                time.sleep(0.05)
            return "<MarkDone>leaf done</MarkDone>", chat_history, {"total_cost": 0.0}

        if "SUB_TASK" in prompt_text:
            return (
                '<SpawnAgent type="worker"><Instructions>LEAF_WORKER</Instructions><Context>c</Context><DoD>d</DoD></SpawnAgent>'
                '<WaitForAgents mode="all" />',
                chat_history,
                {"total_cost": 0.0},
            )

        if "[Completed Child Agent Notifications]" in prompt_text:
            main_saw["prompt"] = prompt_text
            return "<MarkDone>Main recovered</MarkDone>", chat_history, {"total_cost": 0.0}

        return (
            '<SpawnAgent type="sub_orchestrator"><Instructions>SUB_TASK</Instructions><Context>c</Context><DoD>d</DoD></SpawnAgent>'
            '<WaitForAgents mode="all" />',
            chat_history,
            {"total_cost": 0.0},
        )

    state = _make_state(tmp_path)

    def _cancel_sub():
        assert worker_started.wait(timeout=5)
        sub_id = next(iter(state["active_children"].keys()))
        sub_id_holder["id"] = sub_id
        cancelled = cancel_agent_tree(sub_id, reason="Stop sub branch")
        worker_id_holder["cancelled"] = cancelled

    t = threading.Thread(target=_cancel_sub, daemon=True)
    t.start()

    with patch.object(agent_loop, "send_prompt", side_effect=fake_send_prompt), \
         patch.object(agent_loop, "load_prompt", return_value="SYS"):
        res = agent_loop.run_agent(
            agent_type=AgentType.MAIN_ORCHESTRATOR,
            instructions="Launch sub",
            context="",
            dod="Done",
            chat_context_state=state,
            agent_id="main",
        )

    t.join(timeout=5)
    assert res["status"] == "success"
    assert len(worker_id_holder["cancelled"]) == 2
    assert sub_id_holder["id"] in worker_id_holder["cancelled"]
    assert "Stop sub branch" in main_saw["prompt"]


def test_cancel_main_orchestrator_stops_entire_swarm(tmp_path):
    """Cancelling main stops main and cascades to all spawned descendants."""
    worker_started = threading.Event()

    def fake_send_prompt(prompt_text, model, chat_history=None, google_search=False, cancel_event=None):
        chat_history = chat_history or []
        if "CHILD_WORK" in prompt_text:
            worker_started.set()
            for _ in range(100):
                if cancel_event and cancel_event.is_set():
                    raise InterruptedError("cancelled")
                time.sleep(0.05)
            return "<MarkDone>ok</MarkDone>", chat_history, {"total_cost": 0.0}

        return (
            '<SpawnAgent type="worker"><Instructions>CHILD_WORK</Instructions><Context>c</Context><DoD>d</DoD></SpawnAgent>'
            '<WaitForAgents mode="all" />',
            chat_history,
            {"total_cost": 0.0},
        )

    state = _make_state(tmp_path)
    cancelled_list = {}

    def _cancel_main():
        assert worker_started.wait(timeout=5)
        cancelled_list["ids"] = cancel_agent_tree("main", reason="Abort whole run")

    t = threading.Thread(target=_cancel_main, daemon=True)
    t.start()

    with patch.object(agent_loop, "send_prompt", side_effect=fake_send_prompt), \
         patch.object(agent_loop, "load_prompt", return_value="SYS"):
        res = agent_loop.run_agent(
            agent_type=AgentType.MAIN_ORCHESTRATOR,
            instructions="Main task",
            context="",
            dod="Done",
            chat_context_state=state,
            agent_id="main",
        )

    t.join(timeout=5)
    assert res["status"] == "failed"
    assert res["cancelled"] is True
    assert "main" in cancelled_list["ids"]
    assert len(cancelled_list["ids"]) == 2
    assert not is_agent_active("main")


def test_thinking_timeout_excludes_waiting_time(tmp_path):
    """
    Agent has a 0.35s thinking budget. It spawns a child that takes 0.6s while the parent waits.
    Because waiting time is excluded from thinking time, the parent succeeds instead of timing out.
    """
    def fake_send_prompt(prompt_text, model, chat_history=None, google_search=False, cancel_event=None):
        chat_history = chat_history or []
        if "SLOW_CHILD" in prompt_text:
            time.sleep(0.05)
            return "<MarkDone>child ok</MarkDone>", chat_history, {"total_cost": 0.0}

        if "[Completed Child Agent Notifications]" in prompt_text:
            time.sleep(0.05)
            return "<MarkDone>all done</MarkDone>", chat_history, {"total_cost": 0.0}

        time.sleep(0.05)
        return (
            '<SpawnAgent type="worker"><Instructions>SLOW_CHILD</Instructions><Context>c</Context><DoD>d</DoD></SpawnAgent>'
            '<WaitForAgents mode="all" />',
            chat_history,
            {"total_cost": 0.0},
        )

    # Child itself sleeps inside a command, not thinking, OR we slow down child's thread startup
    orig_drain = agent_loop.drain_child_notifications

    def slow_wait_drain(chat_context_state, block_mode=None, cancel_event=None):
        if block_mode == "all":
            time.sleep(0.55)
        return orig_drain(chat_context_state, block_mode=block_mode, cancel_event=cancel_event)

    state = _make_state(tmp_path, thinking_timeout=0.35)
    with patch.object(agent_loop, "send_prompt", side_effect=fake_send_prompt), \
         patch.object(agent_loop, "drain_child_notifications", side_effect=slow_wait_drain), \
         patch.object(agent_loop, "load_prompt", return_value="SYS"):
        res = agent_loop.run_agent(
            agent_type=AgentType.MAIN_ORCHESTRATOR,
            instructions="Wait test",
            context="",
            dod="Done",
            chat_context_state=state,
            agent_id="main",
        )

    assert res["status"] == "success"


def test_thinking_timeout_triggers_on_long_llm_call(tmp_path):
    """Agent times out when active LLM thinking time exceeds the customizable thinking timeout."""
    def slow_think(prompt_text, model, chat_history=None, google_search=False, cancel_event=None):
        time.sleep(1.5)
        return "<MarkDone>too late</MarkDone>", chat_history or [], {"total_cost": 0.0}

    state = _make_state(tmp_path, thinking_timeout=0.25)
    with patch.object(agent_loop, "send_prompt", side_effect=slow_think), \
         patch.object(agent_loop, "load_prompt", return_value="SYS"):
        res = agent_loop.run_agent(
            agent_type=AgentType.WORKER,
            instructions="Think forever",
            context="",
            dod="Done",
            chat_context_state=state,
            agent_id="worker_slow",
        )

    assert res["status"] == "failed"
    assert res["timed_out"] is True
    assert "exceeded its active thinking timeout" in res["result"]
