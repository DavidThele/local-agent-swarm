def execute(attributes: dict, content: dict, context_state: dict) -> str:
    """
    Signals to agent_loop.py that the agent wants to yield its execution turn
    and block until a specific child agent finishes, or based on 'any'/'all' modes.
    """
    agent_id = attributes.get("agent_id")
    
    if agent_id:
        return f"[WAIT_FOR_AGENTS:{agent_id.strip()}]"
        
    mode = str(attributes.get("mode", "any")).lower()
    if mode not in {"any", "all"}:
        return "[Error] WaitForAgents mode must be 'any' or 'all' if no agent_id is specified."
        
    return f"[WAIT_FOR_AGENTS:{mode}]"