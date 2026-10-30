import sys
import queue
from pathlib import Path
from infrastructure.workspace import create_chat_instance
from infrastructure.agent_loop import run_agent
from infrastructure.debug_colors import debug_print

def start_swarm_session(user_prompt: str, chat_id: str = "") -> dict:
    """
    Initializes a local/global symlinked chat workspace and boots the Main Orchestrator.
    """
    chat_id, local_chat_dir = create_chat_instance(chat_id=chat_id)
    
    chat_context_state = {
        "local_chat_dir": str(local_chat_dir),
        "workspace_root": str(Path.cwd().resolve()),
        "worker_id": "main_orchestrator",
        "notification_queue": queue.Queue(),
        "active_children": {}
    }
    
    debug_print(f"[SwarmCLI] Starting session {chat_id}", "system")
    result = run_agent(
        agent_type="MAIN_ORCHESTRATOR",
        instructions=user_prompt,
        context=f"Active Working Directory: {local_chat_dir.parent.parent.parent}",
        dod="Fulfill the user's request completely and accurately, then call <MarkDone>.",
        chat_context_state=chat_context_state,
        agent_id="main"
    )
    
    debug_print(f"\n[SwarmCLI] Session {chat_id} finished with status: {result['status']}", "success")
    print(result["result"])
    return result

if __name__ == "__main__":
    if len(sys.argv) > 1:
        prompt = " ".join(sys.argv[1:])
    else:
        prompt = input("Enter task for the Agent Swarm: ").strip()
        
    if prompt:
        start_swarm_session(prompt)
    else: 
        debug_print("[SwarmCLI] No prompt provided. Exiting.", "error")