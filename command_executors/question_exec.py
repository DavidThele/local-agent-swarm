from infrastructure import ui_bridge
from infrastructure.concurrency import TERMINAL_LOCK

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    if isinstance(content, dict):
        text = content.get("Text", "No question text provided.")
        raw_options = content.get("Options", {})
        if isinstance(raw_options, dict):
            options = raw_options.get("Option", [])
        else:
            options = []
    else:
        text = str(content) if content else "No question text provided."
        options = []

    if isinstance(options, str):
        options = [options] if options else []
    elif not isinstance(options, list):
        options = []

    agent_id = context_state.get("worker_id", "main")
    clean_base = [opt for opt in options if str(opt).strip().lower() != "other"]

    if ui_bridge.is_ui_active():
        res = ui_bridge.request_hitl(
            agent_id=agent_id,
            blocker_type="Question",
            prompt_text=text,
            options=clean_base,
        )
        return f"[User Reply] {res.get('value', '')}"

    clean_options = list(clean_base) + ["Other (type custom response)"]

    with TERMINAL_LOCK:
        print(f"\n[Agent Question from {agent_id}] {text}")
        for i, opt in enumerate(clean_options, 1):
            print(f"  {i}. {opt}")
            
        user_response = input("Select an option number or type your answer: ").strip()
        
        if user_response == str(len(clean_options)):
            user_response = input("Enter your custom answer: ").strip()
        elif user_response.isdigit() and 1 <= int(user_response) < len(clean_options):
            user_response = clean_options[int(user_response) - 1]
            
    return f"[User Reply] {user_response}"