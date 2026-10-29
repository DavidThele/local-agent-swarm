# Command: WaitForAgents

**Description:**
Pauses the current agent's execution loop until background child agents spawned via `<SpawnAgent>` have completed and reported their results. Use this after spawning background agents when you have no more immediate local commands to run.

**Attributes:**
- `mode` (optional): Set to `"any"` to wake up as soon as the next child agent finishes, or `"all"` to wait until all currently active child agents have finished. Defaults to `"any"`.

**Example Usage:**
<WaitForAgents mode="any" />