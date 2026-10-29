def execute(attributes: dict, content: dict, context_state: dict) -> str:
    """
    Signals to agent_loop.py that the agent wants to yield its execution turn
    and block until at least one active background child agent finishes.
    """
    mode = attributes.get("mode", "any").lower()  # "any" or "all"
    return f"[WAIT_FOR_AGENTS:{mode}]"