from infrastructure import ui_bridge
from infrastructure.concurrency import TERMINAL_LOCK

def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    if isinstance(content, dict):
        reason = content.get("Reason", "No reason provided.")
        if isinstance(reason, list):
            reason = reason[0]
    else:
        reason = str(content) if content else "No reason provided."

    agent_id = context_state.get("worker_id", "main")

    if ui_bridge.is_ui_active():
        res = ui_bridge.request_hitl(
            agent_id=agent_id,
            blocker_type="Action",
            prompt_text=reason,
        )
        return f"[System] User intervened and resumed execution. User note: {res.get('value') or 'Proceed.'}"

    with TERMINAL_LOCK:
        print(f"\n[Agent '{agent_id}' is waiting for user intervention]")
        print(f"Reason: {reason}")
        user_response = input("Press Enter to resume execution after resolving the issue, or type a message to the agent: ").strip()
        
    return f"[System] User intervened and resumed execution. User note: {user_response or 'Proceed.'}"