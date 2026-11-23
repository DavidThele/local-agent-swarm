# Global Agents Profile &amp; Context

Foundational system context, user profile, and global rules for all swarm agents.

### Swarm Orchestration &amp; Delegation Rules
- **Discover Before Partitioning:** Never guess file paths or lists. When target files are unknown, list verified paths first, then partition the confirmed list.
- **Parallel Workload Partitioning:** For tasks across over numerous independent files (inspection, summarization, formatting, tests), Orchestrators and Sub-Orchestrators **must** partition the verified file list across 3–5 concurrent workers. Never assign a large multi-file batch to one worker (strict ~10-iteration limit and context saturation).
