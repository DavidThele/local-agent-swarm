from infrastructure.concurrency import TERMINAL_LOCK

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    text = content.get("Text", "No question text provided.")
    options = content.get("Options", {}).get("Option", [])
    agent_id = context_state.get("worker_id", "main")
    
    with TERMINAL_LOCK:
        print(f"\n[Agent Question from {agent_id}] {text}")
        if isinstance(options, list):
            for i, opt in enumerate(options):
                print(f"  {i + 1}. {opt}")
        elif options:
            print(f"  1. {options}")
             
        user_response = input("Your answer: ")
    return f"[User Reply] {user_response}"