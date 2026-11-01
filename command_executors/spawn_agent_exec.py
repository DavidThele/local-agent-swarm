from infrastructure.concurrency import spawn_background_agent
from infrastructure.agent_types import AgentType

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    try:
        agent_type = AgentType.parse(attributes.get("type", AgentType.WORKER.value))
    except ValueError as exc:
        return f"[Error] {exc}"

    instructions = ""
    agent_context = ""
    dod = ""

    if isinstance(content, dict):
        def extract_text(key: str) -> str:
            val = content.get(key, "")
            return val[0] if isinstance(val, list) else val

        instructions = extract_text("Instructions")
        agent_context = extract_text("Context")
        dod = extract_text("DoD")
    else:
        instructions = str(content)

    if not instructions:
        return "[Error] SpawnAgent requires <Instructions>."

    # Launch asynchronously in a background thread
    agent_id = spawn_background_agent(
        agent_type=agent_type,
        instructions=instructions,
        context=agent_context,
        dod=dod,
        parent_context_state=context_state
    )

    print(f"  [SpawnAgent] Launched {agent_type.label} ({agent_id}) asynchronously in background.")
    return (
        f"[System] Successfully spawned {agent_type.label} with ID '{agent_id}' in the background. "
        f"You will receive a notification in a subsequent iteration as soon as '{agent_id}' finishes. "
        f"You may continue executing other commands now, or output <WaitForAgents /> if you have nothing else to do until it completes."
    )