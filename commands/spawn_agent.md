# Command: SpawnAgent

**Description:**
Spawns a new autonomous agent in a background thread to delegate a specific sub-task. Execution returns immediately with the spawned agent's ID so you can spawn multiple agents in parallel or run other commands. Use `<WaitForAgents />` when you are ready to pause and wait for spawned agents to report back.

**Attributes:**
- `type` (required): The role of the spawned agent (e.g., `WORKER`, `SUB_ORCHESTRATOR`).

**Child Tags:**
- `<Instructions>`: The exact step-by-step instructions for the agent to follow.
- `<Context>`: Comprehensive background information containing absolutely everything the agent needs to execute the task (e.g., URLs, absolute paths, known variables, strict naming conventions).
- `<DoD>`: Definition of Done. The strict, explicit criteria the agent must meet before it can mark itself as complete. Must use exact names and paths rather than pronouns.

**Example Usage:**
<SpawnAgent type="WORKER">
    <Instructions>Clone the jumbocode-ui repository using the provided URL into the specified target directory. After cloning, create a new branch using the provided branch name and check it out.</Instructions>
    <Context>
        Task: Initial repository setup for ticket #123.
        Repository URL: https://github.com/JumboCode/jumbocode-ui.git
        Target Clone Directory: /Users/davidthele/Documents/jumbocode-ui
        Target Branch Name: feature/ticket-123-navbar
    </Context>
    <DoD>The jumbocode-ui repository is successfully cloned to the exact path /Users/davidthele/Documents/jumbocode-ui. The branch 'feature/ticket-123-navbar' is created. The branch 'feature/ticket-123-navbar' is currently checked out as the active working branch in the local repository.</DoD>
</SpawnAgent>