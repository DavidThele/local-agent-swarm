import asyncio
import json
import os
import queue
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

load_dotenv()

from command_executors import chrome_exec
from infrastructure import prompt_router, ui_bridge
from infrastructure.agent_loop import (
    AGENT_THINKING_TIMEOUT_SECONDS,
    MAX_ORCHESTRATOR_ITERATIONS,
    MAX_WORKER_ITERATIONS,
    run_agent,
)
from infrastructure.agent_types import AgentType
from infrastructure.concurrency import (
    cancel_agent_tree,
    cancel_all_agents,
    terminate_all_subprocesses,
    wait_for_active_agents,
)
from infrastructure.logging import log
from infrastructure.workspace import create_chat_instance, init_global_workspace
from pipelines.swarm_analyzer import analyze_session
from runtime import DB_DIR, GLOBAL_ROOT, REPO_ROOT, SHUTDOWN_TIMEOUT_SECONDS

UI_DIST_DIR = REPO_ROOT / "swarm-widget-ui" / "dist"

app = FastAPI(title="Local Agent Swarm Bridge")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Server runtime state
_ACTIVE_WORKSPACE: Path = Path.cwd().resolve()
_ACTIVE_CHAT_ID: str = ""
_WS_CLIENTS: set[WebSocket] = set()
_WS_LOCK = asyncio.Lock()
_PIPELINE_THREADS: set[threading.Thread] = set()
_PIPELINE_LOCK = threading.Lock()


async def broadcast_event(message: dict[str, Any]) -> None:
    dead: list[WebSocket] = []
    async with _WS_LOCK:
        clients = list(_WS_CLIENTS)
    for ws in clients:
        try:
            await ws.send_json(message)
        except Exception:
            dead.append(ws)
    if dead:
        async with _WS_LOCK:
            for ws in dead:
                _WS_CLIENTS.discard(ws)


def shutdown_runtime(timeout: float = SHUTDOWN_TIMEOUT_SECONDS) -> None:
    """
    Cancels all active agents, terminates running child subprocess groups,
    joins active swarm threads, and tears down Playwright/browser routers.
    Safe to call multiple times.
    """
    deadline = time.monotonic() + max(0.5, timeout)

    cancelled = cancel_all_agents(reason="Application shutting down.")
    if cancelled:
        log(f"[SwarmServer] Cancelled {len(cancelled)} active agent(s) on shutdown.", "info")

    killed_procs = terminate_all_subprocesses(grace_seconds=1.5)
    if killed_procs:
        log(f"[SwarmServer] Terminated {killed_procs} active subprocess(es) on shutdown.", "info")

    with _PIPELINE_LOCK:
        pipeline_threads = list(_PIPELINE_THREADS)

    for thread in pipeline_threads:
        if thread is threading.current_thread():
            continue
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            break
        if thread.is_alive():
            thread.join(timeout=remaining)

    remaining = max(0.2, deadline - time.monotonic())
    wait_for_active_agents(timeout=remaining)

    try:
        prompt_router.shutdown(timeout=2.5)
    except Exception as exc:
        log(f"[SwarmServer] Prompt router shutdown warning: {exc}", "debug")

    try:
        chrome_exec.shutdown()
    except Exception as exc:
        log(f"[SwarmServer] Chrome executor shutdown warning: {exc}", "debug")


@app.on_event("startup")
async def on_startup() -> None:
    loop = asyncio.get_running_loop()
    ui_bridge.register_bridge(loop, broadcast_event)


@app.on_event("shutdown")
async def on_shutdown() -> None:
    async with _WS_LOCK:
        clients = list(_WS_CLIENTS)
        _WS_CLIENTS.clear()
    for ws in clients:
        try:
            await ws.close(code=1001)
        except Exception:
            pass
    ui_bridge.unregister_bridge()


# ============================================================================
# HELPERS: Session Discovery & Trace Parsing
# ============================================================================
def _check_chroma_status() -> str:
    try:
        db_dir = Path(os.environ.get("AGENTS_DB_DIR", str(DB_DIR))).expanduser()
        return "Connected" if db_dir.exists() else "Offline"
    except Exception:
        return "Offline"


def _format_relative_time(mtime: float) -> str:
    delta = max(0, int(time.time() - mtime))
    if delta < 60:
        return "Just now"
    if delta < 3600:
        return f"{delta // 60}m ago"
    if delta < 86400:
        return f"{delta // 3600}h ago"
    return datetime.fromtimestamp(mtime).strftime("%b %d")


def _map_agent_type_to_ui(raw_type: str) -> str:
    if raw_type == "main_orchestrator":
        return "Main"
    if raw_type == "sub_orchestrator":
        return "Sub"
    return "Worker"


def _find_chat_dir(chat_id: str) -> Path | None:
    global_candidate = GLOBAL_ROOT / "chats" / chat_id
    if global_candidate.exists():
        return global_candidate.resolve()
    local_candidate = _ACTIVE_WORKSPACE / ".agents" / "chats" / chat_id
    if local_candidate.exists():
        return local_candidate.resolve()
    return None


def _summarize_chat_dir(chat_dir: Path) -> dict[str, Any]:
    resolved = chat_dir.resolve()
    global_trace = resolved / "global_trace.json"
    overall_status = "Idle"
    total_cost = 0.0
    title = chat_dir.name.replace("_", " ").title()

    if global_trace.exists():
        try:
            data = json.loads(global_trace.read_text(encoding="utf-8"))
            raw_status = str(data.get("status", "")).lower()
            overall_status = "Success" if raw_status == "success" else "Failed" if raw_status == "failed" else "Idle"
            total_cost = float(data.get("total_cost_usd", 0.0))
        except Exception:
            pass

    # Infer workspace_root from .../<workspace>/.agents/chats/<chat_id>
    workspace_root = str(resolved.parent.parent.parent) if resolved.parent.name == "chats" else str(_ACTIVE_WORKSPACE)

    return {
        "chat_id": chat_dir.name,
        "title": title,
        "workspace_root": workspace_root,
        "overall_status": overall_status,
        "total_cost_usd": round(total_cost, 4),
        "timestamp": _format_relative_time(resolved.stat().st_mtime),
        "chroma_status": _check_chroma_status(),
        "connected_tools": ["Zsh", "FileIO", "ChromeCDP", "ChromaDB"],
    }


# ============================================================================
# REST ENDPOINTS
# ============================================================================
class WorkspaceUpdateReq(BaseModel):
    workspace_root: str


class DeploySwarmReq(BaseModel):
    prompt: str
    attachments: list[str] = []
    workspace_root: str | None = None
    chat_id: str | None = None
    run_optimizer: bool = False


class HitlResolveReq(BaseModel):
    blocker_id: str
    agent_id: str
    action: str
    value: str = ""


class AnalyzeSwarmReq(BaseModel):
    chat_id: str = ""
    user_feedback: str = ""


class CancelAgentReq(BaseModel):
    agent_id: str
    reason: str = "Cancelled by user."


from infrastructure.workspace import IGNORED_DIRS as _IGNORED_DIRS


def _format_analyzer_payload(chat_id: str, analysis: dict[str, Any], duration_sec: float) -> dict[str, Any]:
    return {
        "chat_id": chat_id,
        "efficiency_score": analysis.get("efficiency_score") or "N/A",
        "bottlenecks": analysis.get("bottlenecks") or "None detected.",
        "recommendations": analysis.get("recommendations") or "None.",
        "modifications": analysis.get("modifications", []),
        "cost_usd": round(float(analysis.get("cost_usd", analysis.get("cost", 0.0))), 6),
        "duration_sec": round(duration_sec, 1),
        "user_feedback": analysis.get("user_feedback", ""),
    }


@app.get("/api/config")
def get_config():
    return {
        "workspace_root": str(_ACTIVE_WORKSPACE),
        "chroma_status": _check_chroma_status(),
        "connected_tools": ["Zsh", "FileIO", "ChromeCDP", "ChromaDB"],
        "agent_thinking_timeout_seconds": AGENT_THINKING_TIMEOUT_SECONDS,
    }


@app.post("/api/workspace")
def set_workspace(req: WorkspaceUpdateReq):
    global _ACTIVE_WORKSPACE
    candidate = Path(req.workspace_root).expanduser().resolve()
    if not candidate.exists() or not candidate.is_dir():
        raise HTTPException(status_code=400, detail=f"Directory not found: {candidate}")
    _ACTIVE_WORKSPACE = candidate
    return {"workspace_root": str(_ACTIVE_WORKSPACE)}


@app.post("/api/workspace/pick")
def pick_workspace_folder():
    """Opens native macOS folder picker via osascript and updates active workspace."""
    global _ACTIVE_WORKSPACE
    script = (
        f'POSIX path of (choose folder with prompt "Select Swarm Working Directory" '
        f'default location (POSIX file "{_ACTIVE_WORKSPACE}"))'
    )
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            return {"cancelled": True, "workspace_root": str(_ACTIVE_WORKSPACE)}
        picked = Path(res.stdout.strip()).expanduser().resolve()
        if picked.is_dir():
            _ACTIVE_WORKSPACE = picked
        return {"cancelled": False, "workspace_root": str(_ACTIVE_WORKSPACE)}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"Folder picker failed: {exc}")


@app.get("/api/workspace/files")
def list_workspace_files(q: str = "", limit: int = 40):
    """Lists files inside _ACTIVE_WORKSPACE for @ autocomplete."""
    root = _ACTIVE_WORKSPACE
    if not root.exists() or not root.is_dir():
        return {"files": []}

    query = q.strip().lower()
    matches: list[tuple[int, str]] = []
    max_scan = 4000
    scanned = 0

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(
            d for d in dirnames
            if d not in _IGNORED_DIRS and not d.startswith(".")
        )
        rel_dir = Path(dirpath).relative_to(root)
        for fname in sorted(filenames):
            if fname == ".DS_Store":
                continue
            scanned += 1
            if scanned > max_scan:
                break
            rel_path = (rel_dir / fname).as_posix() if str(rel_dir) != "." else fname
            low_path = rel_path.lower()
            low_name = fname.lower()
            if not query:
                matches.append((2, rel_path))
            elif low_name.startswith(query):
                matches.append((0, rel_path))
            elif query in low_name:
                matches.append((1, rel_path))
            elif query in low_path:
                matches.append((2, rel_path))
        if scanned > max_scan:
            break

    matches.sort(key=lambda item: (item[0], len(item[1]), item[1]))
    return {"files": [path for _, path in matches[:max(1, min(limit, 100))]]}


@app.post("/api/workspace/pick-files")
def pick_workspace_files():
    """Opens native macOS Finder file picker (multi-select) for context attachments."""
    script = (
        f'set chosenFiles to choose file with prompt "Attach Context Files" '
        f'default location (POSIX file "{_ACTIVE_WORKSPACE}") with multiple selections allowed\n'
        f'set output to ""\n'
        f'repeat with f in chosenFiles\n'
        f'  set output to output & (POSIX path of f) & linefeed\n'
        f'end repeat\n'
        f'return output'
    )
    try:
        res = subprocess.run(["osascript", "-e", script], capture_output=True, text=True, timeout=120)
        if res.returncode != 0:
            return {"cancelled": True, "files": []}
        raw_lines = [line.strip() for line in res.stdout.splitlines() if line.strip()]
        formatted: list[str] = []
        for raw in raw_lines:
            p = Path(raw).expanduser().resolve()
            try:
                formatted.append(p.relative_to(_ACTIVE_WORKSPACE).as_posix())
            except ValueError:
                formatted.append(str(p))
        return {"cancelled": False, "files": formatted}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"File picker failed: {exc}")


@app.get("/api/sessions")
def list_sessions():
    init_global_workspace()
    chats_dir = Path.home() / ".agents" / "chats"
    if not chats_dir.exists():
        return []
    entries = []
    for item in chats_dir.iterdir():
        if item.name == "default":
            continue
        try:
            if item.is_dir():
                entries.append((item.resolve().stat().st_mtime, item))
        except OSError:
            continue
    entries.sort(key=lambda pair: pair[0], reverse=True)
    return [_summarize_chat_dir(item) for _, item in entries[:30]]


@app.post("/api/sessions/new")
def create_new_session():
    global _ACTIVE_CHAT_ID
    _ACTIVE_CHAT_ID = ""
    return {
        "chat_id": "",
        "title": "New Session",
        "workspace_root": str(_ACTIVE_WORKSPACE),
        "overall_status": "Idle",
        "total_cost_usd": 0.0,
        "timestamp": "Now",
        "chroma_status": _check_chroma_status(),
        "connected_tools": ["Zsh", "FileIO", "ChromeCDP", "ChromaDB"],
    }


@app.get("/api/sessions/{chat_id}")
def load_session(chat_id: str):
    global _ACTIVE_CHAT_ID, _ACTIVE_WORKSPACE
    chat_dir = _find_chat_dir(chat_id)
    if not chat_dir:
        raise HTTPException(status_code=404, detail=f"Session '{chat_id}' not found")

    _ACTIVE_CHAT_ID = chat_id
    summary = _summarize_chat_dir(chat_dir)
    if Path(summary["workspace_root"]).is_dir():
        _ACTIVE_WORKSPACE = Path(summary["workspace_root"]).resolve()

    agents: list[dict[str, Any]] = []
    logs: list[dict[str, Any]] = []

    for trace_file in sorted(chat_dir.glob("*_trace.json")):
        if trace_file.name == "global_trace.json":
            continue
        try:
            data = json.loads(trace_file.read_text(encoding="utf-8"))
        except Exception:
            continue

        aid = data.get("agent_id", trace_file.stem.replace("_trace", ""))
        atype = _map_agent_type_to_ui(data.get("agent_type", "worker"))
        raw_status = str(data.get("status", "success")).lower()
        ui_status = "completed" if raw_status == "success" else "failed"

        agents.append({
            "agent_id": aid,
            "parent_id": data.get("parent_id", None if atype == "Main" else "main"),
            "type": atype,
            "status": ui_status,
            "current_iteration": data.get("iterations_used", 0),
            "max_iterations": data.get(
                "max_iterations",
                MAX_ORCHESTRATOR_ITERATIONS if atype != "Worker" else MAX_WORKER_ITERATIONS,
            ),
            "cost_usd": round(float(data.get("total_cost_usd", 0.0)), 4),
            "instructions": data.get("instructions", ""),
            "dod": data.get("dod", ""),
        })

        for idx, ev in enumerate(data.get("events", [])):
            logs.append({
                "id": f"{aid}_turn_{idx}",
                "timestamp": data.get("timestamp", "")[11:19] or "--:--:--",
                "agent_id": aid,
                "command_type": "Zsh",
                "payload": ev.get("llm_output", ""),
                "result_output": ev.get("environment_results", ""),
                "is_error": "[Error]" in str(ev.get("environment_results", "")),
            })

    return {"session": summary, "agents": agents, "logs": logs}


@app.post("/api/swarm/deploy")
def deploy_swarm(req: DeploySwarmReq):
    global _ACTIVE_WORKSPACE, _ACTIVE_CHAT_ID

    if req.workspace_root:
        candidate = Path(req.workspace_root).expanduser().resolve()
        if candidate.is_dir():
            _ACTIVE_WORKSPACE = candidate

    requested_chat_id = (req.chat_id or "").strip()
    auto_title = requested_chat_id == ""
    chat_id, local_chat_dir = create_chat_instance(
        chat_id=requested_chat_id,
        workspace_root=_ACTIVE_WORKSPACE,
    )
    _ACTIVE_CHAT_ID = chat_id

    attachments_context = ""
    if req.attachments:
        attachments_context = "\nAttached Context References:\n" + "\n".join(
            f"- {item}" for item in req.attachments
        )

    chat_context_state = {
        "chat_id": chat_id,
        "local_chat_dir": str(local_chat_dir),
        "workspace_root": str(_ACTIVE_WORKSPACE),
        "worker_id": "main",
        "parent_agent_id": None,
        "notification_queue": queue.Queue(),
        "active_children": {},
        "request_chat_title": auto_title,
    }

    ui_bridge.emit(
        "SESSION_UPDATED",
        {
            "chat_id": chat_id,
            "title": req.prompt[:48] + ("..." if len(req.prompt) > 48 else ""),
            "workspace_root": str(_ACTIVE_WORKSPACE),
            "overall_status": "Running",
            "total_cost_usd": 0.0,
        },
    )

    def _run_pipeline():
        started_at = time.time()
        try:
            result = run_agent(
                agent_type=AgentType.MAIN_ORCHESTRATOR,
                instructions=req.prompt,
                context=f"Active Working Directory: {_ACTIVE_WORKSPACE}{attachments_context}",
                dod="Fulfill the user's request completely and accurately, then call <MarkDone>.",
                chat_context_state=chat_context_state,
                agent_id="main",
            )
            final_chat_id = chat_context_state.get("chat_id", chat_id)
            final_chat_dir = chat_context_state.get("local_chat_dir", str(local_chat_dir))
            final_status = "Success" if result.get("status") == "success" else "Failed"

            ui_bridge.emit(
                "SESSION_UPDATED",
                {
                    "chat_id": final_chat_id,
                    "overall_status": final_status,
                },
            )

            if req.run_optimizer and not result.get("cancelled"):
                opt_started = time.time()
                analysis = analyze_session(final_chat_dir)
                if analysis.get("status") == "completed":
                    payload = _format_analyzer_payload(
                        final_chat_id,
                        analysis,
                        time.time() - opt_started,
                    )
                    ui_bridge.emit("ANALYZER_REPORT", payload)
        except Exception as exc:
            log(f"[SwarmServer] Pipeline thread failed: {exc}", "error")
            ui_bridge.emit("SESSION_UPDATED", {"overall_status": "Failed"})
        finally:
            with _PIPELINE_LOCK:
                _PIPELINE_THREADS.discard(threading.current_thread())

    pipeline_thread = threading.Thread(target=_run_pipeline, name=f"swarm_{chat_id}", daemon=True)
    with _PIPELINE_LOCK:
        _PIPELINE_THREADS.add(pipeline_thread)
    pipeline_thread.start()
    return {"chat_id": chat_id, "workspace_root": str(_ACTIVE_WORKSPACE)}


@app.post("/api/swarm/analyze")
def analyze_swarm_session(req: AnalyzeSwarmReq):
    target_chat_id = (req.chat_id or _ACTIVE_CHAT_ID or "").strip()
    if not target_chat_id:
        raise HTTPException(status_code=400, detail="No active chat_id provided for analysis")

    chat_dir = _find_chat_dir(target_chat_id)
    if not chat_dir:
        raise HTTPException(status_code=404, detail=f"Session '{target_chat_id}' not found")

    started_at = time.time()
    try:
        analysis = analyze_session(str(chat_dir), user_feedback=req.user_feedback)
    except Exception as exc:
        log(f"[SwarmServer] Analyzer failed for {target_chat_id}: {exc}", "error")
        raise HTTPException(status_code=500, detail=f"Analyzer failed: {exc}")

    if analysis.get("status") != "completed":
        raise HTTPException(
            status_code=400,
            detail=f"Analyzer skipped: {analysis.get('reason', 'unknown')}",
        )

    payload = _format_analyzer_payload(target_chat_id, analysis, time.time() - started_at)
    ui_bridge.emit("ANALYZER_REPORT", payload)
    return payload


@app.post("/api/swarm/hitl")
def resolve_hitl_http(req: HitlResolveReq):
    ok = ui_bridge.resolve_hitl(req.blocker_id, req.agent_id, req.action, req.value)
    if not ok:
        raise HTTPException(status_code=404, detail="Blocker not found or already resolved")
    return {"status": "resolved"}


@app.post("/api/swarm/cancel")
def cancel_agent_http(req: CancelAgentReq):
    cancelled_ids = cancel_agent_tree(req.agent_id, reason=req.reason)
    if not cancelled_ids:
        raise HTTPException(status_code=404, detail=f"Agent '{req.agent_id}' is not active")
    return {"status": "cancelling", "cancelled_agent_ids": cancelled_ids}


# ============================================================================
# WEBSOCKET STREAM
# ============================================================================
@app.websocket("/ws/swarm")
async def swarm_ws(websocket: WebSocket):
    await websocket.accept()
    async with _WS_LOCK:
        _WS_CLIENTS.add(websocket)
    try:
        while True:
            raw = await websocket.receive_text()
            msg = json.loads(raw)
            msg_type = msg.get("type")
            if msg_type == "HITL_RESPONSE":
                p = msg.get("payload", {})
                ui_bridge.resolve_hitl(
                    blocker_id=p.get("blocker_id", ""),
                    agent_id=p.get("agent_id", ""),
                    action=p.get("action", "deny"),
                    value=p.get("value", ""),
                )
            elif msg_type == "CANCEL_AGENT":
                p = msg.get("payload", {})
                target_id = str(p.get("agent_id", "")).strip()
                if target_id:
                    cancel_agent_tree(
                        target_id,
                        reason=str(p.get("reason") or "Cancelled by user."),
                    )
    except WebSocketDisconnect:
        pass
    finally:
        async with _WS_LOCK:
            _WS_CLIENTS.discard(websocket)


# Serve built React app when `swarm-widget-ui/dist` exists
if UI_DIST_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIST_DIR), html=True), name="ui")