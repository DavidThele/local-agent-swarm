import asyncio
import threading
import uuid
from datetime import datetime
from typing import Any, Callable

# Global singleton state for the active GUI bridge (None when running swarm_cli.py)
_EVENT_LOOP: asyncio.AbstractEventLoop | None = None
_BROADCAST_CALLBACK: Callable[[dict[str, Any]], Any] | None = None

# Pending HITL blockers keyed by blocker_id -> {"event": threading.Event, "resolution": dict}
_PENDING_HITL: dict[str, dict[str, Any]] = {}
_HITL_LOCK = threading.Lock()


def register_bridge(
    loop: asyncio.AbstractEventLoop,
    broadcast_coro_fn: Callable[[dict[str, Any]], Any],
) -> None:
    """Called by swarm_server.py on startup to attach the WebSocket broadcaster."""
    global _EVENT_LOOP, _BROADCAST_CALLBACK
    _EVENT_LOOP = loop
    _BROADCAST_CALLBACK = broadcast_coro_fn


def unregister_bridge() -> None:
    global _EVENT_LOOP, _BROADCAST_CALLBACK
    _EVENT_LOOP = None
    _BROADCAST_CALLBACK = None


def is_ui_active() -> bool:
    return _EVENT_LOOP is not None and _BROADCAST_CALLBACK is not None


def emit(event_type: str, payload: dict[str, Any]) -> None:
    """Thread-safe fire-and-forget WebSocket event emitter (no-op in CLI mode)."""
    if _EVENT_LOOP is None or _BROADCAST_CALLBACK is None:
        return
    message = {"type": event_type, "payload": payload}
    try:
        asyncio.run_coroutine_threadsafe(_BROADCAST_CALLBACK(message), _EVENT_LOOP)
    except RuntimeError:
        pass


def request_hitl(
    agent_id: str,
    blocker_type: str,  # "Security" | "Question" | "Action"
    prompt_text: str,
    command_preview: str | None = None,
    options: list[str] | None = None,
) -> dict[str, Any]:
    """
    Blocks the calling worker thread until the GUI user resolves the HITL prompt.
    Returns {"action": "approve"|"deny"|"answer"|"resume", "value": "..."}.
    """
    blocker_id = f"blk_{uuid.uuid4().hex[:8]}"
    wait_event = threading.Event()

    with _HITL_LOCK:
        _PENDING_HITL[blocker_id] = {
            "event": wait_event,
            "agent_id": agent_id,
            "resolution": None,
        }

    payload: dict[str, Any] = {
        "blocker_id": blocker_id,
        "agent_id": agent_id,
        "blocker_type": blocker_type,
        "prompt_text": prompt_text,
        "timestamp": datetime.now().strftime("%H:%M:%S"),
    }
    if command_preview:
        payload["command_preview"] = command_preview
    if options:
        payload["options"] = options

    emit("HITL_REQUIRED", payload)

    # Also surface the universal upper-right macOS HUD modal so the user can respond
    # from either swarm_gui or the HUD modal (whichever resolves first wins and updates the other).
    from infrastructure import hud_client

    if not hud_client.is_hud_modal_disabled():
        def _hud_prompt_worker() -> None:
            hud_res = hud_client.request_hitl_modal(
                blocker_id=blocker_id,
                blocker_type=blocker_type,
                prompt_text=prompt_text,
                agent_id=agent_id,
                options=options,
                command_preview=command_preview,
            )
            if hud_res.get("action") == "cancelled_externally":
                return
            resolve_hitl(
                blocker_id=blocker_id,
                agent_id=agent_id,
                action=str(hud_res.get("action") or "cancel"),
                value=str(hud_res.get("value") or ""),
                from_hud=True,
            )

        threading.Thread(target=_hud_prompt_worker, daemon=True).start()

    # Block this background agent thread until resolved by the UI or HUD modal
    wait_event.wait()

    with _HITL_LOCK:
        entry = _PENDING_HITL.pop(blocker_id, {})

    return entry.get("resolution") or {"action": "deny", "value": ""}


def resolve_hitl(
    blocker_id: str,
    agent_id: str,
    action: str,
    value: str = "",
    *,
    from_hud: bool = False,
) -> bool:
    """Called by swarm_server.py or the HUD modal when the user submits a HITL resolution."""
    with _HITL_LOCK:
        entry = _PENDING_HITL.get(blocker_id)
        if not entry or entry.get("resolution") is not None:
            return False
        entry["resolution"] = {"action": action, "value": value}
        entry["event"].set()

    emit("HITL_RESOLVED", {"blocker_id": blocker_id, "agent_id": agent_id})
    if not from_hud:
        from infrastructure import hud_client
        hud_client.cancel_hitl_modal(blocker_id)
    return True


def cancel_hitl_for_agents(agent_ids: list[str] | set[str]) -> list[str]:
    """Unblocks any pending HITL prompts belonging to the given cancelled agents."""
    target_ids = set(agent_ids)
    if not target_ids:
        return []

    resolved: list[tuple[str, str]] = []
    with _HITL_LOCK:
        for blocker_id, entry in _PENDING_HITL.items():
            if entry.get("agent_id") in target_ids:
                entry["resolution"] = {"action": "cancel", "value": "Agent cancelled by user."}
                entry["event"].set()
                resolved.append((blocker_id, entry["agent_id"]))

    from infrastructure import hud_client
    for blocker_id, agent_id in resolved:
        emit("HITL_RESOLVED", {"blocker_id": blocker_id, "agent_id": agent_id})
        hud_client.cancel_hitl_modal(blocker_id)

    return [blocker_id for blocker_id, _ in resolved]


def cancel_all_hitl(reason: str = "Application shutting down.") -> list[str]:
    """Unblocks every pending HITL prompt across all agents (used during graceful shutdown)."""
    resolved: list[tuple[str, str]] = []
    with _HITL_LOCK:
        for blocker_id, entry in _PENDING_HITL.items():
            if entry.get("resolution") is None:
                entry["resolution"] = {"action": "cancel", "value": reason}
            entry["event"].set()
            resolved.append((blocker_id, entry.get("agent_id", "")))

    from infrastructure import hud_client
    for blocker_id, agent_id in resolved:
        emit("HITL_RESOLVED", {"blocker_id": blocker_id, "agent_id": agent_id})
        hud_client.cancel_hitl_modal(blocker_id)

    return [blocker_id for blocker_id, _ in resolved]