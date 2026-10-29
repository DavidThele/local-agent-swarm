import importlib
import queue
from pathlib import Path
from infrastructure.prompt_router import send_prompt, GEMINI_3_8_FLASH, GEMINI_3_1_FLASH_LITE
from infrastructure.parser import parse_llm_output

# Maximum times an agent can loop (action -> observe) before being forced to fail.
MAX_ITERATIONS = 12

def load_prompt(role: str) -> str:
    path = Path.home() / ".agents" / "prompts" / f"{role}.md"
    with open(path, "r", encoding="utf-8") as f:
        return f.read()

def drain_child_notifications(chat_context_state: dict, block_mode: str = 'any') -> str:
    """
    Drains any completed child agent results from the parent's notification_queue.
    If block_mode is 'any', blocks until at least 1 active child completes.
    If block_mode is 'all', blocks until all currently active children complete.
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

    # Ensure async tracking structures exist for this agent instance
    if "notification_queue" not in chat_context_state:
        chat_context_state["notification_queue"] = queue.Queue()
    if "active_children" not in chat_context_state:
        chat_context_state["active_children"] = {}

    system_prompt = load_prompt(agent_type.lower())

    # Initialize the agent's first prompt with its assignment
    current_prompt = f"{system_prompt}\n\n"
    current_prompt += f"=== YOUR ASSIGNMENT ===\n"
    current_prompt += f"<Instructions>{instructions}</Instructions>\n"
    current_prompt += f"<Context>{context}</Context>\n"
    if dod:
        current_prompt += f"<DoD>{dod}</DoD>\n"

    model_to_use = GEMINI_3_8_FLASH if agent_type.upper() == "MAIN_ORCHESTRATOR" else GEMINI_3_1_FLASH_LITE
    chat_history = []

    for iteration in range(MAX_ITERATIONS):
        # 0. Check if any background child agents finished before sending prompt
        async_updates = drain_child_notifications(chat_context_state, block_mode='any')
        if async_updates:
            current_prompt += f"\n{async_updates}"

        print(f"[{agent_type}:{agent_id}] Iteration {iteration + 1}/{MAX_ITERATIONS} - Thinking...")

        # 1. Get LLM Output
        llm_output, chat_history, cost = send_prompt(
            prompt_text=current_prompt,
            model=model_to_use,
            chat_history=chat_history
        )

        # 2. Parse Commands
        commands = parse_llm_output(llm_output)

        if not commands:
            # If the agent has active children running and outputted no commands, auto-wait for the next child
            if chat_context_state["active_children"]:
                current_prompt = drain_child_notifications(chat_context_state, block_mode="any")
                continue
            current_prompt = "[System Error] No valid XML commands found in your last output. You must use a command or <MarkDone>."
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
                executor = importlib.import_module(f"command_executors.{module_name}")

                cmd_result = executor.execute(cmd.attributes, cmd.content, chat_context_state)

                # Handle WaitForAgents signal
                if cmd_result.startswith("[WAIT_FOR_AGENTS:"):
                    wait_mode = cmd_result.split(":")[1].rstrip("]")
                    continue

                # Check if the agent called MarkDone
                if cmd_result.startswith("[STATUS_DONE]"):
                    # Guardrail: Prevent parent from marking done while child threads are still running
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
            print(f"[{agent_type}:{agent_id}] Task Completed Successfully.")
            return {"status": "success", "result": final_result}

        # 4. If the agent requested <WaitForAgents />, block here until child notifications arrive
        if wait_mode:
            if chat_context_state["active_children"]:
                wait_updates = drain_child_notifications(chat_context_state, block_mode=wait_mode)
                results_string += f"\n{wait_updates}"
            else:
                results_string += "\n[System] <WaitForAgents> called, but no active child agents are running.\n"

        current_prompt = results_string

    print(f"[{agent_type}:{agent_id}] HIT HARD ITERATION CAP ({MAX_ITERATIONS}). Terminating loop.")
    return {"status": "failed", "result": "[System Error] Agent hit the maximum iteration limit without completing the DoD."}