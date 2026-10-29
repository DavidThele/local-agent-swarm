def execute(attributes: dict, content: dict, context_state: dict) -> str:
    # Import inside the function to prevent circular dependency at load time
    from infrastructure.agent_loop import run_agent

    agent_type = attributes.get("type", "WORKER")
    
    # Safely extract nested XML content
    instructions = ""
    agent_context = ""
    dod = ""

    if isinstance(content, dict):
        # Helper to unpack single strings vs lists of strings from the parser
        def extract_text(key: str) -> str:
            val = content.get(key, "")
            return val[0] if isinstance(val, list) else val
            
        instructions = extract_text("Instructions")
        agent_context = extract_text("Context")
        dod = extract_text("DoD")
    else:
        # Fallback if the LLM outputted raw text instead of nested tags
        instructions = str(content)

    if not instructions:
        return "[Error] SpawnAgent requires <Instructions>."

    print(f"\n[SpawnAgent] Delegating sub-task to {agent_type}...")
    
    # Trigger the recursive agent loop!
    result_dict = run_agent(
        agent_type=agent_type,
        instructions=instructions,
        context=agent_context,
        dod=dod,
        chat_context_state=context_state
    )

    status = result_dict.get("status")
    final_output = result_dict.get("result", "No final output returned.")

    if status == "success":
        return f"--- [CHILD AGENT {agent_type}: SUCCESS] ---\n{final_output}"
    else:
        return f"--- [CHILD AGENT {agent_type}: FAILED] ---\n{final_output}"