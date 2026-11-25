import os
import queue
import signal
import subprocess
import threading
import time
import uuid
from typing import Any
from infrastructure import ui_bridge
from infrastructure.agent_types import AgentType

# Global lock to prevent multiple background threads from asking for terminal input() simultaneously
TERMINAL_LOCK = threading.Lock()

# Thread-safe registry of currently active agents and their parent-child hierarchy
# agent_id -> {"parent_id": str|None, "agent_type": str, "cancel_event": Event, "cancel_reason": str|None, "children": set[str]}
_AGENT_REGISTRY: dict[str, dict[str, Any]] = {}
_REGISTRY_LOCK = threading.Lock()

# Thread-safe registry of active child subprocesses (e.g., Zsh commands) for clean shutdown
_ACTIVE_SUBPROCESSES: set[subprocess.Popen] = set()
_SUBPROCESS_LOCK = threading.Lock()

# Thread-safe registry of spawned background agent threads
_ACTIVE_AGENT_THREADS: set[threading.Thread] = set()
_THREADS_LOCK = threading.Lock()


def register_subprocess(proc: subprocess.Popen) -> None:
    """Tracks an active subprocess so graceful shutdown can terminate its process group."""
    with _SUBPROCESS_LOCK:
        _ACTIVE_SUBPROCESSES.add(proc)


def unregister_subprocess(proc: subprocess.Popen) -> None:
    """Removes a finished subprocess from the active tracker."""
    with _SUBPROCESS_LOCK:
        _ACTIVE_SUBPROCESSES.discard(proc)


def terminate_process_group(proc: subprocess.Popen, grace_seconds: float = 2.0) -> None:
    """
    Gracefully terminates a subprocess and its entire process group (SIGTERM -> SIGKILL).
    Safe to call even if the process already exited.
    """
    if proc.poll() is not None:
        return

    pgid: int | None = None
    if os.name == "posix":
        try:
            pgid = os.getpgid(proc.pid)
        except (ProcessLookupError, OSError):
            pgid = None

    # Only signal the process group if it is isolated from our own process group
    own_pgid = os.getpgrp() if os.name == "posix" else None
    use_pgid = pgid is not None and pgid != own_pgid

    try:
        if use_pgid and pgid is not None:
            os.killpg(pgid, signal.SIGTERM)
        else:
            proc.terminate()
    except (ProcessLookupError, OSError):
        return

    try:
        proc.wait(timeout=grace_seconds)
        return
    except subprocess.TimeoutExpired:
        pass

    try:
        if use_pgid and pgid is not None:
            os.killpg(pgid, signal.SIGKILL)
        else:
            proc.kill()
    except (ProcessLookupError, OSError):
        pass

    try:
        proc.wait(timeout=1.0)
    except subprocess.TimeoutExpired:
        pass


def terminate_all_subprocesses(grace_seconds: float = 1.5) -> int:
    """Terminates all tracked active subprocesses and their process groups."""
    with _SUBPROCESS_LOCK:
        procs = list(_ACTIVE_SUBPROCESSES)

    terminated = 0
    for proc in procs:
        if proc.poll() is None:
            terminate_process_group(proc, grace_seconds=grace_seconds)
            terminated += 1
        unregister_subprocess(proc)
    return terminated


def register_agent(
    agent_id: str,
    parent_id: str | None,
    agent_type: AgentType | str,
    cancel_event: threading.Event | None = None,
) -> threading.Event:
    """Registers an active agent in the hierarchy registry and returns its cancel_event."""
    role = AgentType.parse(agent_type)
    with _REGISTRY_LOCK:
        existing = _AGENT_REGISTRY.get(agent_id)
        if existing is not None:
            if parent_id and existing["parent_id"] is None:
                existing["parent_id"] = parent_id
            if parent_id and parent_id in _AGENT_REGISTRY:
                _AGENT_REGISTRY[parent_id]["children"].add(agent_id)
            return existing["cancel_event"]

        ev = cancel_event if cancel_event is not None else threading.Event()
        cancel_reason: str | None = None

        if parent_id and parent_id in _AGENT_REGISTRY:
            parent_entry = _AGENT_REGISTRY[parent_id]
            parent_entry["children"].add(agent_id)
            if parent_entry["cancel_event"].is_set():
                ev.set()
                cancel_reason = (
                    parent_entry["cancel_reason"]
                    or f"Cancelled because parent agent '{parent_id}' was cancelled."
                )

        _AGENT_REGISTRY[agent_id] = {
            "agent_id": agent_id,
            "parent_id": parent_id,
            "agent_type": role.value,
            "cancel_event": ev,
            "cancel_reason": cancel_reason,
            "children": set(),
        }
        return ev


def unregister_agent(agent_id: str) -> None:
    """Removes a finished agent from the active registry."""
    with _REGISTRY_LOCK:
        entry = _AGENT_REGISTRY.pop(agent_id, None)
        if entry:
            parent_id = entry.get("parent_id")
            if parent_id and parent_id in _AGENT_REGISTRY:
                _AGENT_REGISTRY[parent_id]["children"].discard(agent_id)


def get_cancel_reason(agent_id: str) -> str | None:
    """Returns the cancellation reason recorded for an active agent, if any."""
    with _REGISTRY_LOCK:
        entry = _AGENT_REGISTRY.get(agent_id)
        return entry.get("cancel_reason") if entry else None


def is_agent_active(agent_id: str) -> bool:
    with _REGISTRY_LOCK:
        return agent_id in _AGENT_REGISTRY


def cancel_agent_tree(agent_id: str, reason: str = "Cancelled by user.") -> list[str]:
    """
    Cancels the target agent and recursively cancels all active descendants
    spawned off it (workers and sub-orchestrators).
    Returns the list of cancelled agent_ids (empty if agent_id is not active).
    """
    cancelled_ids: list[str] = []
    with _REGISTRY_LOCK:
        if agent_id not in _AGENT_REGISTRY:
            return []

        stack = [agent_id]
        visited: set[str] = set()
        while stack:
            current_id = stack.pop()
            if current_id in visited:
                continue
            visited.add(current_id)
            entry = _AGENT_REGISTRY.get(current_id)
            if not entry:
                continue
            cancelled_ids.append(current_id)
            if entry["cancel_reason"] is None:
                if current_id == agent_id:
                    entry["cancel_reason"] = reason
                else:
                    entry["cancel_reason"] = (
                        f"Cancelled because parent agent '{agent_id}' was cancelled."
                    )
            entry["cancel_event"].set()
            for child_id in entry["children"]:
                if child_id not in visited:
                    stack.append(child_id)

    # Unblock any HITL prompts held by the cancelled agents
    ui_bridge.cancel_hitl_for_agents(cancelled_ids)
    return cancelled_ids


def cancel_all_agents(reason: str = "Application shutting down.") -> list[str]:
    """
    Cancels every currently active agent in the registry and unblocks all pending HITL prompts.
    Used during graceful application shutdown.
    """
    cancelled_ids: list[str] = []
    with _REGISTRY_LOCK:
        for agent_id, entry in _AGENT_REGISTRY.items():
            cancelled_ids.append(agent_id)
            if entry["cancel_reason"] is None:
                entry["cancel_reason"] = reason
            entry["cancel_event"].set()

    ui_bridge.cancel_all_hitl(reason=reason)
    return cancelled_ids


def wait_for_active_agents(timeout: float = 3.0) -> bool:
    """Waits up to `timeout` seconds for all spawned background agent threads to exit."""
    deadline = time.monotonic() + max(0.0, timeout)
    with _THREADS_LOCK:
        threads = list(_ACTIVE_AGENT_THREADS)

    for t in threads:
        if t is threading.current_thread():
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if t.is_alive():
            t.join(timeout=remaining)

    with _THREADS_LOCK:
        alive = [t for t in _ACTIVE_AGENT_THREADS if t.is_alive() and t is not threading.current_thread()]
    return len(alive) == 0


def spawn_background_agent(
    agent_type: AgentType | str,
    instructions: str,
    context: str,
    dod: str,
    parent_context_state: dict
) -> str:
    """
    Spawns run_agent in a daemon thread and hooks its completion up to the parent's notification_queue.
    Returns the generated agent_id immediately without blocking.
    """
    from infrastructure.agent_loop import run_agent

    agent_type = AgentType.parse(agent_type)

    agent_id = f"{agent_type.id_prefix}_{uuid.uuid4().hex[:6]}"
    parent_id = parent_context_state.get("worker_id", "main")
    parent_queue: queue.Queue = parent_context_state["notification_queue"]
    active_children: dict = parent_context_state["active_children"]

    # Register before thread start so parent cancellation immediately cascades without a race window
    child_cancel_event = register_agent(
        agent_id=agent_id,
        parent_id=parent_id,
        agent_type=agent_type,
    )

    # Create an isolated context_state for the child so its own children report to IT, not the grandparent
    child_context_state = {
        "local_chat_dir": parent_context_state.get("local_chat_dir", ".agents/chats/default"),
        "workspace_root": parent_context_state.get("workspace_root"),
        "worker_id": agent_id,
        "parent_agent_id": parent_id,
        "notification_queue": queue.Queue(),
        "active_children": {},
        "cancel_event": child_cancel_event,
    }
    if "thinking_timeout_seconds" in parent_context_state:
        child_context_state["thinking_timeout_seconds"] = parent_context_state["thinking_timeout_seconds"]

    def _thread_target():
        try:
            result_dict = run_agent(
                agent_type=agent_type,
                instructions=instructions,
                context=context,
                dod=dod,
                chat_context_state=child_context_state,
                agent_id=agent_id
            )
            status = result_dict.get("status", "failed").upper()
            output = result_dict.get("result", "No output returned.")
        except Exception as e:
            status = "ERROR"
            output = f"Unhandled exception in agent thread: {str(e)}"
        finally:
            unregister_agent(agent_id)
            with _THREADS_LOCK:
                _ACTIVE_AGENT_THREADS.discard(threading.current_thread())

        # Notify the parent agent via its thread-safe queue
        notification_msg = (
            f"--- [ASYNC CHILD AGENT COMPLETED: {agent_id} ({agent_type.label}) | STATUS: {status}] ---\n"
            f"{output}\n"
        )
        parent_queue.put((agent_id, notification_msg))

    # Register child as active before starting thread
    thread = threading.Thread(target=_thread_target, name=agent_id, daemon=True)
    with _THREADS_LOCK:
        _ACTIVE_AGENT_THREADS.add(thread)
    active_children[agent_id] = {
        "type": agent_type.value,
        "thread": thread,
        "dod": dod,
        "cancel_event": child_cancel_event,
    }
    thread.start()

    return agent_id