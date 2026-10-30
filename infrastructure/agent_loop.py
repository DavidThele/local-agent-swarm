import importlib
import json
import queue
from datetime import datetime
from pathlib import Path
from infrastructure.prompt_router import send_prompt, GEMINI_3_8_FLASH, GEMINI_3_1_FLASH_LITE
from infrastructure.parser import parse_llm_output

MAX_ITERATIONS = 12

# Role-based command access table
ROLE_COMMANDS = {
    "main_orchestrator": ["search_db", "spawn_agent", "wait_for_agents", "question", "mark_done"],
    "sub_orchestrator": ["spawn_agent", "wait_for_agents", "mark_done"],
    "worker": ["zsh", "write_file", "read_file", "list_directory", "mark_done"],
}

def _resolve_resource_file(relative_path: str) -> Path:
    """Checks ~/.agents first, then falls back to the repository root."""
    global_path = Path.home() / ".agents" / relative_path
    if global_path.exists():
        return global_path
    return Path(__file__).resolve().parents[1] / relative_path

def load_prompt(role: str) -> str:
    """
    Loads the global AGENTS.md context, the role's system prompt, 
    and the markdown schemas for all commands available to that role.
    """
    role_key = role.lower()
    sections = []
    
    # 1. Global AGENTS.md profile
    agents_md = _resolve_resource_file("AGENTS.md")
    if agents_md.exists():
        sections.append(agents_md.read_text(encoding="utf-8").strip())
        
    # 2. Role-specific prompt
    role_path = _resolve_resource_file(f"prompts/{role_key}.md")
    if not role_path.exists():
        raise FileNotFoundError(f"Role prompt not found: {role_path}")
    sections.append(role_path.read_text(encoding="utf-8").strip())
    
    # 3. Inject available command documentation
    allowed_cmds = ROLE_COMMANDS.get(role_key, [])
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
    agent_type: str,
    instructions: str,
    dod: str,
    status: str,
    iterations_used: int,
    total_cost: float,
    trace_events: list
):
    """Saves a JSON log of the agent's turns and costs into local_chat_dir for Phase 5 analysis."""
    chat_dir = Path(chat_context_state.get("local_chat_dir", ".agents/chats/default"))
    chat_dir.mkdir(parents=True, exist_ok=True)
    
    trace_file = chat_dir / f"{agent_id}_trace.json"
    payload = {
        "agent_id": agent_id,
        "agent_type": agent_type,
        "timestamp": datetime.now().isoformat(),
        "status": status,
        "iterations_used": iterations_used,
        "max_iterations": MAX_ITERATIONS,
        "total_cost_usd": round(total_cost, 6),
        "instructions": instructions,
        "dod": dod,
        "events": trace_events,
    }
    with open(trace_file, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)

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
        print(f"  [AsyncWait] Waiting for next child agent to finish (Active: {list(active_children.keys())})...")
        child_id, msg = notif_queue.get(block=True)
        active_children.pop(child_id, None)
        messages.append(msg)

    elif block_mode == "all" and active_children:
        print(f"  [AsyncWait] Waiting for ALL {len(active_children)} child agents to finish...")
        while active_children:
            child_id, msg = notif_queue.get(block=True)
            active_children.pop(child_id, None)
            messages.append(msg)

    # Always drain any remaining notifications that finished simultaneously
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
    agent_type: str,
    instructions: str,
    context: str,
    dod: str,
    chat_context_state: dict,
    agent_id: str = "main"
) -> dict:
    """
    The core execution loop for a single agent.
    """
    print(f"\n[Swarm] Booting {agent_type.upper()} ({agent_id})...")

    if "notification_queue" not in chat_context_state:
        chat_context_state["notification_queue"] = queue.Queue()
    if "active_children" not in chat_context_state:
        chat_context_state["active_children"] = {}
    chat_context_state.setdefault("workspace_root", str(Path.cwd().resolve()))

    system_prompt = load_prompt(agent_type.lower())

    current_prompt = f"{system_prompt}\n\n"
    current_prompt += "=== YOUR ASSIGNMENT ===\n"
    current_prompt += f"<Instructions>{instructions}</Instructions>\n"
    current_prompt += f"<Context>{context}</Context>\n"
    if dod:
        current_prompt += f"<DoD>{dod}</DoD>\n"

    model_to_use = GEMINI_3_8_FLASH if agent_type.upper() == "MAIN_ORCHESTRATOR" else GEMINI_3_1_FLASH_LITE
    chat_history = []
    trace_events = []
    cumulative_cost = 0.0

    for iteration in range(MAX_ITERATIONS):
        # 0. Non-blocking check if any background child agents finished before sending prompt
        async_updates = drain_child_notifications(chat_context_state, block_mode=None)
        if async_updates:
            current_prompt += f"\n{async_updates}"

        print(f"[{agent_type}:{agent_id}] Iteration {iteration + 1}/{MAX_ITERATIONS} - Thinking...")

        # 1. Get LLM Output
        llm_output, chat_history, cost = send_prompt(
            prompt_text=current_prompt,
            model=model_to_use,
            chat_history=chat_history
        )
        if isinstance(cost, dict):
            cumulative_cost += cost.get("total_cost", 0.0)

        # 2. Parse Commands
        commands = parse_llm_output(llm_output)

        if not commands:
            if chat_context_state["active_children"]:
                current_prompt = drain_child_notifications(chat_context_state, block_mode="any")
                continue
            current_prompt = "[System Error] No valid XML commands found in your last output. You must use a command or <MarkDone>."
            trace_events.append({
                "iteration": iteration + 1,
                "llm_output": llm_output,
                "environment_results": current_prompt
            })
            continue

        # 3. Execute Commands
        results_string = "\n[System Environment Results]\n"
        is_done = False
        final_result = None
        wait_mode = None

        for cmd in commands:
            print(f"  [{agent_id}] -> Executing <{cmd.command}>...")

            try:
                module_name = ''.join(['_'+c.lower() if c.isupper() else c for c in cmd.command]).lstrip('_') + "_exec"
                allowed_commands = ROLE_COMMANDS.get(agent_type.lower(), [])
                command_name = module_name.removesuffix("_exec")
                if command_name not in allowed_commands:
                    results_string += (
                        f"[Error] Command <{cmd.command}> is not allowed for role "
                        f"{agent_type}.\n\n"
                    )
                    continue
                executor = importlib.import_module(f"command_executors.{module_name}")

                cmd_result = executor.execute(cmd.attributes, cmd.content, chat_context_state)

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

        if is_done:
            trace_events.append({
                "iteration": iteration + 1,
                "llm_output": llm_output,
                "environment_results": final_result
            })
            save_agent_trace(
                chat_context_state, agent_id, agent_type, instructions,
                dod, "success", iteration + 1, cumulative_cost, trace_events
            )
            print(f"[{agent_type}:{agent_id}] Task Completed Successfully.")
            return {"status": "success", "result": final_result}

        # 4. If the agent requested <WaitForAgents />, block here until child notifications arrive
        if wait_mode:
            if chat_context_state["active_children"]:
                wait_updates = drain_child_notifications(chat_context_state, block_mode=wait_mode)
                results_string += f"\n{wait_updates}"
            else:
                results_string += "\n[System] <WaitForAgents> called, but no active child agents are running.\n"

        trace_events.append({
            "iteration": iteration + 1,
            "llm_output": llm_output,
            "environment_results": results_string.strip()
        })
        current_prompt = results_string

    save_agent_trace(
        chat_context_state, agent_id, agent_type, instructions,
        dod, "failed", MAX_ITERATIONS, cumulative_cost, trace_events
    )
    print(f"[{agent_type}:{agent_id}] HIT HARD ITERATION CAP ({MAX_ITERATIONS}). Terminating loop.")
    return {"status": "failed", "result": "[System Error] Agent hit the maximum iteration limit without completing the DoD."}