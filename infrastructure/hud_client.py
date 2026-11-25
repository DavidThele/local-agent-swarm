"""Client for presenting interactive HITL modals via the resident HUD service (with subprocess fallback)."""

from __future__ import annotations

import fcntl
import json
import os
import socket
import subprocess
import sys
import threading
import uuid
from pathlib import Path
from typing import Any

from runtime import (
    HITL_FALLBACK_LOCK_PATH as FALLBACK_LOCK_PATH,
    MACRO_SERVICE_SOCKET as SOCKET_PATH,
)

_ACTIVE_SUBPROCS_LOCK = threading.Lock()
_ACTIVE_SUBPROCS: dict[str, subprocess.Popen] = {}


def is_hud_modal_disabled() -> bool:
    if os.environ.get("AGENTS_DISABLE_HUD_MODAL", "").strip().lower() in {"1", "true", "yes"}:
        return True
    if os.environ.get("PYTEST_CURRENT_TEST"):
        return True
    return False


def send_macos_notification(title: str, message: str) -> None:
    """Display a native macOS notification banner (best-effort, non-blocking)."""
    if sys.platform != "darwin" or is_hud_modal_disabled():
        return
    safe_title = title.replace("\\", "\\\\").replace('"', '\\"')
    safe_msg = message.replace("\\", "\\\\").replace('"', '\\"')
    script = f'display notification "{safe_msg}" with title "{safe_title}"'
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def _request_via_resident_service(payload: dict[str, Any]) -> dict[str, Any] | None:
    """Send a JSON request to the resident MacroService socket and wait for the JSON response."""
    from infrastructure.logging import log

    if not SOCKET_PATH.exists():
        log(f"[HudClient] Resident socket not found at {SOCKET_PATH}", "warning")
        return None
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(3.0)
            client.connect(str(SOCKET_PATH))
            client.sendall((json.dumps(payload) + "\n").encode("utf-8"))
            # Wait indefinitely for user response (no timeout)
            client.settimeout(None)
            chunks: list[bytes] = []
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break
        raw = b"".join(chunks).decode("utf-8", errors="replace").strip()
        if not raw:
            log(f"[HudClient] Empty reply from resident socket {SOCKET_PATH}", "warning")
            return None
        return json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        log(f"[HudClient] Resident socket {SOCKET_PATH} failed: {exc}", "warning")
        return None


def _request_via_subprocess_fallback(payload: dict[str, Any]) -> dict[str, Any]:
    """Notify user that resident HUD service is not running, then spawn a queued standalone modal."""
    send_macos_notification(
        "Resident HUD Service Not Running",
        "MacroService is not started; using standalone modal fallback.",
    )
    blocker_id = str(payload.get("blocker_id") or "")
    FALLBACK_LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(FALLBACK_LOCK_PATH, "a+", encoding="utf-8") as lock_file:
        # Cross-process FIFO queue: only one standalone modal appears at a time
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        proc = None
        try:
            proc = subprocess.Popen(
                [sys.executable, "-m", "macro_synth.hud.hitl_modal"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            if blocker_id:
                with _ACTIVE_SUBPROCS_LOCK:
                    _ACTIVE_SUBPROCS[blocker_id] = proc
            stdout, _ = proc.communicate(json.dumps(payload))
            lines = [ln.strip() for ln in (stdout or "").splitlines() if ln.strip()]
            for line in reversed(lines):
                if line.startswith("{"):
                    return json.loads(line)
            return {"action": "cancelled_externally", "value": ""}
        except Exception:
            return {"action": "cancel", "value": ""}
        finally:
            if blocker_id:
                with _ACTIVE_SUBPROCS_LOCK:
                    _ACTIVE_SUBPROCS.pop(blocker_id, None)
            try:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass


def request_hitl_modal(
    *,
    blocker_type: str,
    prompt_text: str,
    agent_id: str = "agent",
    options: list[str] | None = None,
    command_preview: str | None = None,
    blocker_id: str | None = None,
) -> dict[str, Any]:
    """
    Present an upper-right macOS HUD modal for Question, Security, or Action prompts.
    Uses the resident MacroService if available; otherwise notifies the user and falls back
    to a standalone subprocess modal.
    """
    bid = blocker_id or f"hud_{uuid.uuid4().hex[:8]}"
    payload: dict[str, Any] = {
        "type": "hitl_modal",
        "blocker_id": bid,
        "blocker_type": blocker_type,
        "agent_id": agent_id,
        "prompt_text": prompt_text,
        "options": list(options or []),
        "command_preview": command_preview or "",
    }

    res = _request_via_resident_service(payload)
    if res is not None:
        return res

    return _request_via_subprocess_fallback(payload)


def cancel_hitl_modal(blocker_id: str) -> None:
    """Dismiss an active or queued HUD modal (e.g. when resolved in swarm_gui)."""
    if not blocker_id:
        return

    with _ACTIVE_SUBPROCS_LOCK:
        proc = _ACTIVE_SUBPROCS.pop(blocker_id, None)
    if proc is not None and proc.poll() is None:
        try:
            proc.terminate()
        except Exception:
            pass

    if not SOCKET_PATH.exists():
        return
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(1.5)
            client.connect(str(SOCKET_PATH))
            cancel_msg = {"type": "cancel_hitl", "blocker_id": blocker_id}
            client.sendall((json.dumps(cancel_msg) + "\n").encode("utf-8"))
    except OSError:
        pass
