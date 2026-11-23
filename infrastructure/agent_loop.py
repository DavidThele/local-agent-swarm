import importlib
import json
import queue
import uuid
from datetime import datetime
from pathlib import Path
from infrastructure import ui_bridge
from infrastructure.logging import log
from infrastructure.prompt_router import send_prompt
from infrastructure.parser import parse_llm_output
from infrastructure.agent_types import AgentType

MAX_WORKER_ITERATIONS = 50
MAX_ORCHESTRATOR_ITERATIONS = 100

def _resolve_resource_file(relative_path: str) -> Path:
    """Checks ~/.agents first, then falls back to the repository root."""
    global_path = Path.home() / ".agents" / relative_path
    if global_path.exists():
        return global_path
    return Path(__file__).resolve().parents[1] / relative_path

def load_prompt(agent_type: AgentType | str) -> str:
    """
    Loads the global AGENTS.md context, the role's system prompt, 
    and the markdown schemas for all commands available to that role.
    """
    role = AgentType.parse(agent_type)
    sections = []
    
    # 1. Global AGENTS.md profile
    agents_md = _resolve_resource_file("AGENTS.md")
    if agents_md.exists():
        sections.append(agents_md.read_text(encoding="utf-8").strip())
        
    # 2. Role-specific prompt
    role_path = _resolve_resource_file(f"prompts/{role.prompt_filename}")
    if not role_path.exists():
        raise FileNotFoundError(f"Role prompt not found: {role_path}")
    sections.append(role_path.read_text(encoding="utf-8").strip())
    
    # 3. Inject available command documentation
    allowed_cmds = role.commands
    if allowed_cmds:
        cmd_docs = ["## Available XML Commands\nYou may ONLY use the following XML commands:"]
        for cmd_name in allowed_cmds:
            cmd_path = _resolve_resource_file(f"commands/{cmd_name}.md")
            if cmd_path.exists():
                cmd_docs.append(cmd_path.read_text(encoding="utf-8").strip())
        sections.append("\n\n---\n\n".join(cmd_docs))
        
    return "\n\n========================================\n\n".join(sections)

def save_agent_trace(
    chat_context_state: dict,
    agent_id: str,
    agent_type: AgentType | str,
    instructions: str,
    dod: str,
    status: str,
    iterations_used: int,
    total_cost: float,
    trace_events: list
):
    """Saves a JSON log of the agent's turns and costs into local_chat_dir for Phase 5 analysis."""
    agent_type = AgentType.parse(agent_type)
    chat_dir = Path(chat_context_state.get("local_chat_dir", ".agents/chats/default"))
    chat_dir.mkdir(parents=True, exist_ok=True)
    
    trace_file = chat_dir / f"{agent_id}_trace.json"
    payload = {
        "agent_id": agent_id,
        "parent_id": chat_context_state.get("parent_agent_id"),
        "agent_type": agent_type.value,
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "iterations_used": iterations_used,
        "max_iterations": MAX_ORCHESTRATOR_ITERATIONS if agent_type in (AgentType.MAIN_ORCHESTRATOR, AgentType.SUB_ORCHESTRATOR) else MAX_WORKER_ITERATIONS,
        "total_cost_usd": round(total_cost, 6),
        "instructions": instructions,
        "dod": dod,
        "events": trace_events,
    }
    with open(trace_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

def save_global_trace(chat_context_state: dict, final_status: str = "success"):
    """
    Scans all agent trace files (*_trace.json) in chat_dir and compiles 
    a consolidated global trace including all main and sub-agents.
    """
    chat_dir = Path(chat_context_state.get("local_chat_dir", ".agents/chats/default"))
    if not chat_dir.exists():
        return

    all_events = []
    total_cost = 0.0
    total_iters = 0
    overall_status = final_status

    trace_files = list(chat_dir.glob("*_trace.json"))
    
    for trace_file in sorted(trace_files):
        if trace_file.name == "global_trace.json":
            continue
        try:
            with open(trace_file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            total_cost += data.get("total_cost_usd", 0.0)
            total_iters += data.get("iterations_used", 0)
            
            if data.get("status") == "failed":
                overall_status = "failed"
                
            agent_id = data.get("agent_id", "unknown")
            instructions = data.get("instructions", "")
            
            for event in data.get("events", []):
                event_copy = dict(event)
                if "agent_id" not in event_copy:
                    event_copy["agent_id"] = agent_id
                if "instructions" not in event_copy:
                    event_copy["instructions"] = instructions
                all_events.append(event_copy)
        except Exception as e:
            log(f"[Warning] Failed to read trace file {trace_file.name}: {e}", "warning")

    global_payload = {
        "timestamp": datetime.now().isoformat(),
        "status": overall_status,
        "total_iters": total_iters,
        "total_cost_usd": round(total_cost, 6),
        "events": all_events
    }

    global_trace_file = chat_dir / "global_trace.json"
    with open(global_trace_file, "w", encoding="utf-8") as f:
        json.dump(global_payload, f, indent=2)

def drain_child_notifications(chat_context_state: dict, block_mode: str | None = None) -> str:
    """
    Drains any completed child agent results from the parent's notification_queue.
    - block_mode=None: Non-blocking poll (returns immediately if queue is empty).
    - block_mode='any': Blocks until at least 1 active child completes.
    - block_mode='all': Blocks until all currently active children complete.
    """
    notif_queue: queue.Queue = chat_context_state["notification_queue"]
    active_children: dict = chat_context_state["active_children"]
    messages = []

    if block_mode == "any" and active_children and notif_queue.empty():
        log(f"  [AsyncWait] Waiting for next child agent to finish (Active: {list(active_children.keys())})...", "warning")
        child_id, msg = notif_queue.get(block=True)
        active_children.pop(child_id, None)
        messages.append(msg)

    elif block_mode == "all" and active_children:
        log(f"  [AsyncWait] Waiting for ALL {len(active_children)} child agents to finish...", "warning")
        while active_children:
            child_id, msg = notif_queue.get(block=True)
            active_children.pop(child_id, None)
            messages.append(msg)

    while not notif_queue.empty():
        try:
            child_id, msg = notif_queue.get_nowait()
            active_children.pop(child_id, None)
            messages.append(msg)
        except queue.Empty:
            break

    if messages:
        return "\n[Completed Child Agent Notifications]\n" + "\n".join(messages) + "\n"
    return ""

def run_agent(
    agent_type: AgentType | str,
    instructions: str,
    context: str,
    dod: str,
    chat_context_state: dict,
    agent_id: str = "main"
) -> dict:
    """
    The core execution loop for a single agent.
    """
    agent_type = AgentType.parse(agent_type)
    log(f"\n[Swarm] Booting {agent_type.label} ({agent_id})...", "system")

    if "notification_queue" not in chat_context_state:
        chat_context_state["notification_queue"] = queue.Queue()
    if "active_children" not in chat_context_state:
        chat_context_state["active_children"] = {}
    
    chat_context_state.setdefault("workspace_root", str(Path.cwd().resolve()))
    chat_context_state["worker_id"] = agent_id

    max_iters = (
        MAX_ORCHESTRATOR_ITERATIONS
        if agent_type in (AgentType.MAIN_ORCHESTRATOR, AgentType.SUB_ORCHESTRATOR)
        else MAX_WORKER_ITERATIONS
    )
    ui_role = (
        "Main"
        if agent_type is AgentType.MAIN_ORCHESTRATOR
        else "Sub"
        if agent_type is AgentType.SUB_ORCHESTRATOR
        else "Worker"
    )

    ui_bridge.emit(
        "AGENT_SPAWNED",
        {
            "agent_id": agent_id,
            "parent_id": chat_context_state.get("parent_agent_id"),
            "type": ui_role,
            "status": "booting",
            "current_iteration": 0,
            "max_iterations": max_iters,
            "cost_usd": 0.0,
            "instructions": instructions,
            "dod": dod,
        },
    )

    system_prompt = load_prompt(agent_type)

    current_prompt = f"{system_prompt}\n\n"
    current_prompt += "=== YOUR ASSIGNMENT ===\n"
    current_prompt += f"<Instructions>{instructions}</Instructions>\n"
    current_prompt += f"<Context>{context}</Context>\n"
    if dod:
        current_prompt += f"<DoD>{dod}</DoD>\n"
    if agent_type is AgentType.MAIN_ORCHESTRATOR and chat_context_state.get("request_chat_title"):
        current_prompt += (
            "\n[System Note] Because this is the start of a new session, include a "
            "<ChatTitle>brief 2-5 word title</ChatTitle> tag in your first response "
            "to name this conversation directory.\n"
        )

    model_to_use = agent_type.model
    chat_history = []
    trace_events = []
    past_events = []
    cumulative_cost = 0.0
    past_iterations = 0

    # -------------------------------------------------------------------------
    # RESUME HISTORY LOGIC
    # -------------------------------------------------------------------------
    chat_dir = Path(chat_context_state.get("local_chat_dir", ""))
    trace_file = chat_dir / f"{agent_id}_trace.json"

    if trace_file.exists():
        try:
            with open(trace_file, "r", encoding="utf-8") as f:
                past_data = json.load(f)
            
            try:
                from google.genai import types
                
                past_instructions = past_data.get("instructions", "")
                past_dod = past_data.get("dod", "")
                past_events = past_data.get("events", [])
                cumulative_cost = past_data.get("total_cost_usd", 0.0)
                past_iterations = past_data.get("iterations_used", 0)
                
                first_user_text = f"[Archived System Prompt Elided]\n=== PAST ASSIGNMENT ===\n<Instructions>{past_instructions}</Instructions>\n<DoD>{past_dod}</DoD>"
                
                for i, ev in enumerate(past_events):
                    user_text = first_user_text if i == 0 else past_events[i-1].get("environment_results", "[No Results]")
                    chat_history.append(types.Content(role="user", parts=[types.Part.from_text(text=user_text)]))
                    chat_history.append(types.Content(role="model", parts=[types.Part.from_text(text=ev.get("llm_output", ""))]))
                    
                if past_events:
                    log(f"[Swarm] Resumed session with {len(past_events)} past turns for {agent_id}.", "system")
                    
            except ImportError:
                log("[Swarm] Could not import google.genai.types to reconstruct history.", "warning")
        except Exception as e:
            log(f"[Swarm] Failed to load past chat history: {e}", "warning")

    # -------------------------------------------------------------------------

    for iteration in range(max_iters):
        async_updates = drain_child_notifications(chat_context_state, block_mode=None)
        if async_updates:
            current_prompt += f"\n{async_updates}"

        log(f"[{agent_type.value}:{agent_id}] Iteration {iteration + 1}/{max_iters} - Thinking...", "system")
        ui_bridge.emit(
            "AGENT_UPDATED",
            {
                "agent_id": agent_id,
                "status": "booting",
                "current_iteration": iteration + 1,
                "cost_usd": round(cumulative_cost, 4),
            },
        )

        turn_prompt_chars = len(current_prompt)
        llm_output, chat_history, cost = send_prompt(
            prompt_text=current_prompt,
            model=model_to_use,
            chat_history=chat_history,
            google_search=True,
        )
        
        turn_cost = 0.0
        turn_tokens = {
            "input_tokens": 0,
            "output_tokens": 0,
            "thinking_tokens": 0,
            "total_tokens": 0,
        }
        if isinstance(cost, dict):
            turn_cost = cost.get("total_cost", 0.0)
            turn_tokens = {
                "input_tokens": int(cost.get("input_tokens", 0) or 0),
                "output_tokens": int(cost.get("output_tokens", 0) or 0),
                "thinking_tokens": int(cost.get("thinking_tokens", 0) or 0),
                "total_tokens": int(cost.get("total_tokens", 0) or 0),
            }
        elif isinstance(cost, (int, float)):
            turn_cost = float(cost)
            
        cumulative_cost += turn_cost

        ui_bridge.emit(
            "AGENT_UPDATED",
            {
                "agent_id": agent_id,
                "status": "executing",
                "current_iteration": iteration + 1,
                "cost_usd": round(cumulative_cost, 4),
            },
        )

        commands = parse_llm_output(llm_output)

        if not commands:
            if chat_context_state["active_children"]:
                ui_bridge.emit("AGENT_UPDATED", {"agent_id": agent_id, "status": "waiting"})
                current_prompt = drain_child_notifications(chat_context_state, block_mode="any")
                continue
            current_prompt = "[System Error] No valid XML commands found in your last output. You must use a command or <MarkDone>."
            
            trace_events.append({
                "iteration": iteration + 1,
                "llm_output": llm_output,
                "environment_results": current_prompt,
                "turn_cost_usd": round(turn_cost, 6),
                "prompt_chars": turn_prompt_chars,
                "llm_output_chars": len(llm_output or ""),
                "env_results_chars": len(current_prompt),
                **turn_tokens,
            })
            continue

        results_string = "\n[System Environment Results]\n"
        is_done = False
        final_result = None
        wait_mode = None

        for cmd in commands:
            log(f"  [{agent_id}] -> Executing <{cmd.command}>...", "system")

            try:
                module_name = ''.join(['_'+c.lower() if c.isupper() else c for c in cmd.command]).lstrip('_') + "_exec"
                allowed_commands = agent_type.commands
                command_name = module_name.removesuffix("_exec")
                if command_name not in allowed_commands:
                    results_string += (
                        f"[Error] Command <{cmd.command}> is not allowed for role "
                        f"{agent_type.value}.\n\n"
                    )
                    continue
                executor = importlib.import_module(f"command_executors.{module_name}")

                cmd_result = executor.execute(cmd.attributes, cmd.content, chat_context_state)

                ui_bridge.emit(
                    "COMMAND_LOGGED",
                    {
                        "id": f"cmd_{uuid.uuid4().hex[:8]}",
                        "timestamp": datetime.now().strftime("%H:%M:%S"),
                        "agent_id": agent_id,
                        "command_type": cmd.command,
                        "attributes": cmd.attributes,
                        "payload": cmd.raw,
                        "result_output": cmd_result,
                        "is_error": cmd_result.startswith("[Error]") or "DENIED" in cmd_result,
                    },
                )

                if cmd_result.startswith("[WAIT_FOR_AGENTS:"):
                    wait_mode = cmd_result.split(":")[1].rstrip("]")
                    continue

                if cmd_result.startswith("[STATUS_DONE]"):
                    if chat_context_state["active_children"]:
                        active_ids = list(chat_context_state["active_children"].keys())
                        results_string += (
                            f"[System Error] Cannot <MarkDone> while child agents are still running in the background: "
                            f"{active_ids}. Use <WaitForAgents mode=\"all\" /> first.\n\n"
                        )
                        continue
                    is_done = True
                    final_result = cmd_result
                    break

                results_string += f"--- Result of <{cmd.command}> ---\n{cmd_result}\n\n"

            except ModuleNotFoundError:
                results_string += f"[Error] Command <{cmd.command}> does not exist or has no executor.\n"
            except Exception as e:
                results_string += f"[Error] Failed to execute <{cmd.command}>: {str(e)}\n"

        env_res_str = final_result if is_done else results_string.strip()
        trace_events.append({
            "iteration": iteration + 1,
            "llm_output": llm_output,
            "environment_results": env_res_str,
            "turn_cost_usd": round(turn_cost, 6),
            "prompt_chars": turn_prompt_chars,
            "llm_output_chars": len(llm_output or ""),
            "env_results_chars": len(env_res_str or ""),
            **turn_tokens,
        })

        if is_done:
            save_agent_trace(
                chat_context_state, agent_id, agent_type, instructions,
                dod, "success", past_iterations + iteration + 1, cumulative_cost, past_events + trace_events
            )
            save_global_trace(chat_context_state, final_status="success")
            ui_bridge.emit(
                "AGENT_UPDATED",
                {
                    "agent_id": agent_id,
                    "status": "completed",
                    "current_iteration": iteration + 1,
                    "cost_usd": round(cumulative_cost, 4),
                },
            )
            log(f"[{agent_type.value}:{agent_id}] Task Completed Successfully.", "success")
            return {"status": "success", "result": final_result}

        if wait_mode:
            if chat_context_state["active_children"]:
                ui_bridge.emit("AGENT_UPDATED", {"agent_id": agent_id, "status": "waiting"})
                wait_updates = drain_child_notifications(chat_context_state, block_mode=wait_mode)
                results_string += f"\n{wait_updates}"
            else:
                results_string += "\n[System] <WaitForAgents> called, but no active child agents are running.\n"

        current_prompt = results_string

    save_agent_trace(
        chat_context_state, agent_id, agent_type, instructions,
        dod, "failed", past_iterations + max_iters, cumulative_cost, past_events + trace_events
    )
    save_global_trace(chat_context_state, final_status="failed")
    ui_bridge.emit(
        "AGENT_UPDATED",
        {
            "agent_id": agent_id,
            "status": "failed",
            "current_iteration": max_iters,
            "cost_usd": round(cumulative_cost, 4),
            "error_line": f"Agent hit maximum iteration limit ({max_iters}/{max_iters}).",
        },
    )
    log(f"[{agent_type.value}:{agent_id}] HIT HARD ITERATION CAP ({max_iters}). Terminating loop.", "error")
    return {"status": "failed", "result": "[System Error] Agent hit the maximum iteration limit without completing the DoD."}