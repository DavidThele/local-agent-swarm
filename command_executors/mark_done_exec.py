def execute(attributes: dict, content: dict, context_state: dict) -> str:
    result = content.get("Result", "No result provided.")
    summary = content.get("Summary", "No summary provided.")
    
    # The main agent loop will check if the return string starts with "[STATUS_DONE]"
    # to terminate the agent's cycle and pass the result back up.
    return f"[STATUS_DONE]\nResult: {result}\nSummary: {summary}"