import sys
from pathlib import Path
from datetime import datetime
from infrastructure.prompt_router import send_prompt, GEMINI_3_8_FLASH
from infrastructure.parser import parse_llm_output
from infrastructure.debug_colors import debug_print

GLOBAL_ROOT = Path.home() / ".agents"
REPO_ROOT = Path(__file__).resolve().parents[1]
HISTORY_DIR = GLOBAL_ROOT / "prompts" / "agents_prompt_history"

def load_optimizer_prompt() -> str:
    """Loads optimizer_instructions.md from ~/.agents/prompts or falls back to repo prompts/."""
    global_prompt = GLOBAL_ROOT / "prompts" / "optimizer_instructions.md"
    if global_prompt.exists():
        return global_prompt.read_text(encoding="utf-8")
        
    repo_prompt = REPO_ROOT / "prompts" / "optimizer_instructions.md"
    if repo_prompt.exists():
        return repo_prompt.read_text(encoding="utf-8")
        
    raise FileNotFoundError(f"Optimizer instructions not found at {global_prompt} or {repo_prompt}")

def collect_session_artifacts(chat_dir: Path) -> str:
    """Gathers all *_trace.json and *_summary.txt files from the chat session directory."""
    if not chat_dir.exists():
        raise FileNotFoundError(f"Chat session directory not found: {chat_dir}")

    artifacts = []
    
    for trace_file in sorted(chat_dir.glob("*_trace.json")):
        content = trace_file.read_text(encoding="utf-8")
        artifacts.append(f"=== TRACE FILE: {trace_file.name} ===\n{content}")

    for summary_file in sorted(chat_dir.glob("*_summary.txt")):
        content = summary_file.read_text(encoding="utf-8")
        artifacts.append(f"=== WORKER FILE SUMMARY: {summary_file.name} ===\n{content}")

    return "\n\n".join(artifacts)

def snapshot_agents_history(current_content: str, summary_msg: str):
    """
    Saves a timestamped copy of AGENTS.md into ~/.agents/prompts/agents_prompt_history/
    instead of relying on a git repository.
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create a clean filename slug from the summary message
    slug = "".join(c if c.isalnum() else "_" for c in summary_msg).strip("_")[:30]
    filename = f"agents_{timestamp}_{slug}.md"
    
    snapshot_path = HISTORY_DIR / filename
    snapshot_path.write_text(current_content, encoding="utf-8")
    debug_print(f"[Optimizer] Saved prompt history snapshot: {snapshot_path}", "system")

def analyze_session(chat_id_or_path: str) -> dict:
    """
    Runs the Phase 5 Performance Analyzer on a completed chat session.
    Accepts either a path to a chat directory or a chat_id string.
    """
    candidate_path = Path(chat_id_or_path).expanduser()
    if candidate_path.exists() and candidate_path.is_dir():
        chat_dir = candidate_path
    else:
        chat_dir = GLOBAL_ROOT / "chats" / chat_id_or_path

    debug_print(f"\n[Optimizer] Auditing session artifacts in {chat_dir}...", "info")
    session_logs = collect_session_artifacts(chat_dir)

    if not session_logs.strip():
        debug_print("[Optimizer] No trace or summary files found in session directory. Skipping analysis.", "warning")
        return {"status": "skipped", "reason": "no_artifacts"}

    # Resolve AGENTS.md (prefer ~/.agents/AGENTS.md, fallback to repo AGENTS.md)
    agents_md_path = GLOBAL_ROOT / "AGENTS.md" if (GLOBAL_ROOT / "AGENTS.md").exists() else REPO_ROOT / "AGENTS.md"
    current_agents_md = agents_md_path.read_text(encoding="utf-8") if agents_md_path.exists() else ""

    skills_dir = GLOBAL_ROOT / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    existing_skills = [p.stem for p in skills_dir.glob("*.md")]

    sys_prompt = load_optimizer_prompt()
    full_prompt = (
        f"{sys_prompt}\n\n"
        f"<CurrentAgentsMd>\n{current_agents_md}\n</CurrentAgentsMd>\n\n"
        f"<ExistingSkills>{', '.join(existing_skills) if existing_skills else 'None'}</ExistingSkills>\n\n"
        f"<SessionTelemetry>\n{session_logs}\n</SessionTelemetry>\n\n"
        "Analyze the session telemetry above and emit your XML optimization commands."
    )

    llm_output, _, cost = send_prompt(prompt_text=full_prompt, model=GEMINI_3_8_FLASH)
    commands = parse_llm_output(llm_output)

    report_summary = {}
    modifications = []

    for cmd in commands:
        if cmd.command == "EvaluationReport" and isinstance(cmd.content, dict):
            report_summary = cmd.content
            score = report_summary.get("EfficiencyScore", "N/A")
            bottlenecks = report_summary.get("Bottlenecks", "None")
            recs = report_summary.get("Recommendations", "None")
            debug_print(f"[Optimizer] Efficiency Score: {score}", "info")
            debug_print(f"[Optimizer] Bottlenecks: {bottlenecks}", "warning")
            debug_print(f"[Optimizer] Recommendations: {recs}", "data")

        elif cmd.command == "UpdateAgentsMd":
            if isinstance(cmd.content, dict):
                new_content = cmd.content.get("Content", "").strip()
                summary = cmd.content.get("Summary", "Updated AGENTS.md")
            else:
                new_content = str(cmd.content).strip()
                summary = "Updated AGENTS.md"

            if new_content:
                # Save a backup in the chat session folder before overwriting
                (chat_dir / "AGENTS_md_backup.md").write_text(current_agents_md, encoding="utf-8")
                
                # Write the new version to AGENTS.md
                agents_md_path.write_text(new_content + "\n", encoding="utf-8")
                if REPO_ROOT / "AGENTS.md" != agents_md_path and (REPO_ROOT / "AGENTS.md").exists():
                    (REPO_ROOT / "AGENTS.md").write_text(new_content + "\n", encoding="utf-8")
                
                # Snapshot the new version to the history folder instead of git commit
                snapshot_agents_history(new_content + "\n", summary)
                
                modifications.append(summary)
                debug_print(f"[Optimizer] Upgraded AGENTS.md: {summary}", "success")

        elif cmd.command == "UpsertSkill":
            skill_name = cmd.attributes.get("name", "").strip().lower().replace(" ", "_")
            if isinstance(cmd.content, dict):
                skill_body = cmd.content.get("Content", "").strip()
                summary = cmd.content.get("Summary", f"Upserted skill {skill_name}")
            else:
                skill_body = str(cmd.content).strip()
                summary = f"Upserted skill {skill_name}"

            if skill_name and skill_body:
                skill_path = skills_dir / f"{skill_name}.md"
                skill_path.write_text(skill_body + "\n", encoding="utf-8")
                modifications.append(summary)
                debug_print(f"[Optimizer] Saved skill '{skill_path.name}': {summary}", "success")

    report_file = chat_dir / "optimizer_report.txt"
    total_cost = cost.get("total_cost", 0.0) if isinstance(cost, dict) else 0.0
    report_file.write_text(
        f"Timestamp: {datetime.now().isoformat()}\nCost: ${total_cost:.6f}\n\n{llm_output}",
        encoding="utf-8"
    )

    return {
        "status": "completed",
        "report": report_summary,
        "modifications": modifications,
        "cost": total_cost
    }

if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_session(sys.argv[1])
    else:
        print("Usage: python3 -m pipelines.performance_analyzer <chat_id_or_path>")