import sys
import queue
from pathlib import Path
from infrastructure.workspace import create_chat_instance
from infrastructure.agent_loop import run_agent
from infrastructure.agent_types import AgentType
from infrastructure.debugging import debug_print
from pipelines.swarm_analyzer import analyze_session

def start_swarm_session(user_prompt: str, chat_id: str = "", run_optimizer: bool | None = None) -> dict:
    """
    Initializes a local/global symlinked chat workspace, boots the Main Orchestrator,
    and optionally runs the Phase 5 Performance Analyzer post-mortem upon completion.
    """
    auto_title = (chat_id == "")
    chat_id, local_chat_dir = create_chat_instance(chat_id=chat_id)
    
    chat_context_state = {
        "chat_id": chat_id,
        "local_chat_dir": str(local_chat_dir),
        "workspace_root": str(Path.cwd().resolve()),
        "worker_id": AgentType.MAIN_ORCHESTRATOR.id_prefix,
        "notification_queue": queue.Queue(),
        "active_children": {},
        "request_chat_title": auto_title,
    }
    
    debug_print(f"[SwarmCLI] Starting session {chat_id}", "system")
    result = run_agent(
        agent_type=AgentType.MAIN_ORCHESTRATOR,
        instructions=user_prompt,
        context=f"Active Working Directory: {local_chat_dir.parent.parent.parent}",
        dod="Fulfill the user's request completely and accurately, then call <MarkDone>.",
        chat_context_state=chat_context_state,
        agent_id="main"
    )
    
    final_chat_id = chat_context_state.get("chat_id", chat_id)
    final_chat_dir = chat_context_state.get("local_chat_dir", str(local_chat_dir))
    
    debug_print(f"\n[SwarmCLI] Session {final_chat_id} finished with status: {result['status']}", "success")
    print(result["result"])

    # Ask interactively if run_optimizer wasn't explicitly set to True/False
    if run_optimizer is None:
        run_optimizer = input("\nRun Performance Analyzer? [y/n]: ").strip().lower() == "y"

    if run_optimizer:
        try:
            analyze_session(final_chat_dir)
        except Exception as e:
            debug_print(f"[SwarmCLI] Optimizer post-mortem failed: {e}", "warning")

    return result

if __name__ == "__main__":
    prompt = input("Enter task for the Agent Swarm: ").strip()
        
    if prompt:
        start_swarm_session(prompt)
    else: 
        debug_print("[SwarmCLI] No prompt provided. Exiting.", "error")