import threading
import queue
import uuid

# Global lock to prevent multiple background threads from asking for terminal input() simultaneously
TERMINAL_LOCK = threading.Lock()

def spawn_background_agent(
    agent_type: str,
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

    agent_id = f"{agent_type.lower()}_{uuid.uuid4().hex[:6]}"
    parent_queue: queue.Queue = parent_context_state["notification_queue"]
    active_children: dict = parent_context_state["active_children"]

    # Create an isolated context_state for the child so its own children report to IT, not the grandparent
    child_context_state = {
        "local_chat_dir": parent_context_state.get("local_chat_dir", ".agents/chats/default"),
        "workspace_root": parent_context_state.get("workspace_root"),
        "worker_id": agent_id,
        "notification_queue": queue.Queue(),
        "active_children": {}
    }

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

        # Notify the parent agent via its thread-safe queue
        notification_msg = (
            f"--- [ASYNC CHILD AGENT COMPLETED: {agent_id} ({agent_type}) | STATUS: {status}] ---\n"
            f"{output}\n"
        )
        parent_queue.put((agent_id, notification_msg))

    # Register child as active before starting thread
    thread = threading.Thread(target=_thread_target, name=agent_id, daemon=True)
    active_children[agent_id] = {
        "type": agent_type,
        "thread": thread,
        "dod": dod
    }
    thread.start()

    return agent_id