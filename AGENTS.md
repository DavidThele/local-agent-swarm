# Global Agents Profile & Context

This file contains the foundational system context, user profile, and global rules for all agents in the swarm. 

> **Note:** The Optimizer agent will append and modify this file dynamically.

___

User preferences and rules are appended below in as much specificity as possible:

### Swarm Orchestration & Delegation Rules
- **Parallel Workload Partitioning:**
  - When a task involves processing multiple independent files (e.g., file inspection, batch summarization, formatting, or test generation across >5 files), Orchestrators and Sub-Orchestrators **must** partition the file list and spawn multiple concurrent workers (e.g., 3–5 workers) in parallel.
  - Never delegate a large multi-file batch to a single worker, as workers have strict iteration limits (typically 10 iterations) and accumulated file reads lead to context window saturation and unnecessary cost.
___
