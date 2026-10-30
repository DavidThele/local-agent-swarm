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

    # Strip any duplicate "Other" from LLM output and hardcode "Other" as the final option
    clean_options = [opt for opt in options if str(opt).strip().lower() != "other"]
    clean_options.append("Other (type custom response)")

    agent_id = context_state.get("worker_id", "main")
    
    with TERMINAL_LOCK:
        print(f"\n[Agent Question from {agent_id}] {text}")
        for i, opt in enumerate(clean_options, 1):
            print(f"  {i}. {opt}")
            
        user_response = input("Select an option number or type your answer: ").strip()
        
        # If user selected the "Other" number, prompt for their custom text
        if user_response == str(len(clean_options)):
            user_response = input("Enter your custom answer: ").strip()
        elif user_response.isdigit() and 1 <= int(user_response) < len(clean_options):
            user_response = clean_options[int(user_response) - 1]
            
    return f"[User Reply] {user_response}"