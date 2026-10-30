def execute(attributes: dict, content: dict, context_state: dict) -> str:
    if isinstance(content, dict):
        result = content.get("Result", "No result provided.")
        summary = content.get("Summary", "No summary provided.")
    else:
        result = str(content) if content else "No result provided."
        summary = "Completed."
        
    return f"[STATUS_DONE]\nResult: {result}\nSummary: {summary}"