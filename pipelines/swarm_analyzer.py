import json
import re
import sys
from pathlib import Path
from datetime import datetime
from infrastructure.prompt_router import send_prompt
from infrastructure.models import GEMINI_3_8_FLASH
from infrastructure.parser import parse_llm_output
from infrastructure.logging import log
from pipelines.performance_analyzer import snapshot_prompt_history

GLOBAL_ROOT = Path.home() / ".agents"
REPO_ROOT = Path(__file__).resolve().parents[1]

_ROLE_SORT_ORDER = {
    "main_orchestrator": 0,
    "sub_orchestrator": 1,
    "worker": 2,
}


def load_optimizer_prompt() -> str:
    global_prompt = GLOBAL_ROOT / "prompts" / "swarm_analyzer_instructions.md"
    if global_prompt.exists():
        return global_prompt.read_text(encoding="utf-8")

    repo_prompt = REPO_ROOT / "prompts" / "swarm_analyzer_instructions.md"
    if repo_prompt.exists():
        return repo_prompt.read_text(encoding="utf-8")

    raise FileNotFoundError(
        f"Swarm analyzer instructions not found at {global_prompt} or {repo_prompt}"
    )


def _clip(text: object, max_len: int) -> str:
    compact = re.sub(r"\s+", " ", str(text or "")).strip()
    if len(compact) <= max_len:
        return compact
    return compact[: max_len - 3].rstrip() + "..."


def _summarize_command(cmd) -> str:
    """Produces a concise 1-line description of an agent's XML command with no file-write bodies."""
    name = cmd.command
    attrs = cmd.attributes or {}
    content = cmd.content

    if name == "WriteFile":
        path = attrs.get("path") or (content.get("Path") if isinstance(content, dict) else "")
        mode = attrs.get("mode") or (content.get("Mode") if isinstance(content, dict) else "")
        parts = [f"path={path}"] if path else []
        if mode:
            parts.append(f"mode={mode}")
        return f"WriteFile({', '.join(parts)})" if parts else "WriteFile"

    if name == "ReadFile":
        path = attrs.get("path") or (content.get("Path") if isinstance(content, dict) else str(content or ""))
        start = attrs.get("start_line") or attrs.get("start")
        end = attrs.get("end_line") or attrs.get("end")
        rng = f":{start}-{end}" if start or end else ""
        return f"ReadFile({_clip(path, 120)}{rng})"

    if name == "ListDirectory":
        path = attrs.get("path") or (content.get("Path") if isinstance(content, dict) else str(content or "."))
        return f"ListDirectory({_clip(path, 120)})"

    if name == "Zsh":
        shell_cmd = content.get("Command", "") if isinstance(content, dict) else str(content or "")
        return f"Zsh({_clip(shell_cmd, 140)})"

    if name == "SearchDB":
        query = attrs.get("query") or (content.get("Query") if isinstance(content, dict) else str(content or ""))
        return f"SearchDB({_clip(query, 120)})"

    if name == "Chrome":
        action = attrs.get("action") or (content.get("Action") if isinstance(content, dict) else "")
        url = attrs.get("url") or (content.get("Url") if isinstance(content, dict) else "")
        bits = [b for b in (action, _clip(url, 80) if url else "") if b]
        return f"Chrome({', '.join(bits)})" if bits else "Chrome"

    if name == "SpawnAgent":
        role = attrs.get("type") or attrs.get("role") or ""
        target_id = attrs.get("id") or attrs.get("name") or ""
        instr = content.get("Instructions", "") if isinstance(content, dict) else ""
        header = ", ".join(b for b in (role, target_id) if b)
        snippet = f" -> {_clip(instr, 120)}" if instr else ""
        return f"SpawnAgent({header}){snippet}"

    if name == "WaitForAgents":
        mode = attrs.get("mode", "all")
        return f"WaitForAgents(mode={mode})"

    if name == "Question":
        q_text = content.get("Text", "") if isinstance(content, dict) else str(content or "")
        return f"Question({_clip(q_text, 160)})"

    if name == "MarkDone":
        if isinstance(content, dict):
            summary = content.get("Summary") or content.get("Result") or ""
        else:
            summary = str(content or "")
        return f"MarkDone({_clip(summary, 240)})"

    if name == "ChatTitle":
        return f"ChatTitle({_clip(str(content or ''), 60)})"

    attr_str = ", ".join(f"{k}={_clip(v, 40)}" for k, v in list(attrs.items())[:4])
    return f"{name}({attr_str})" if attr_str else name


def _extract_signals_only(env_results: str) -> list[str]:
    """
    Extracts ONLY high-signal metadata from environment_results (never raw command outputs):
    - User replies to <Question> prompts (for AGENTS.md preference codification)
    - Short 1-line system/security/command error headers (no stdout/file dumps)
    """
    if not env_results:
        return []

    signals: list[str] = []
    for raw_line in str(env_results).splitlines():
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("[User Reply]"):
            signals.append(_clip(line, 200))
        elif (
            line.startswith("[Error]")
            or line.startswith("[System Error]")
            or "DENIED" in line
            or "[SECURITY" in line
        ):
            signals.append(_clip(line, 140))

    # Deduplicate while preserving order, cap to 4 signals per turn
    seen: set[str] = set()
    deduped: list[str] = []
    for s in signals:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
        if len(deduped) >= 4:
            break
    return deduped


def build_curated_session_digest(chat_dir: Path) -> str:
    """
    Builds an ultra-concise, curated digest of a swarm session for the analyzer.
    Excludes raw trace JSONs, global_trace.json, *_summary.txt, command outputs,
    and WriteFile contents.
    """
    if not chat_dir.exists():
        raise FileNotFoundError(f"Chat session directory not found: {chat_dir}")

    traces: list[dict] = []
    for trace_file in sorted(chat_dir.glob("*_trace.json")):
        if trace_file.name == "global_trace.json":
            continue
        try:
            traces.append(json.loads(trace_file.read_text(encoding="utf-8")))
        except Exception as exc:
            log(f"[SwarmAnalyzer] Skipping unreadable trace {trace_file.name}: {exc}", "warning")

    if not traces:
        return ""

    traces.sort(
        key=lambda t: (
            _ROLE_SORT_ORDER.get(str(t.get("agent_type", "worker")), 2),
            str(t.get("agent_id", "")),
        )
    )

    total_iters = sum(int(t.get("iterations_used", 0)) for t in traces)
    total_cost = sum(float(t.get("total_cost_usd", 0.0)) for t in traces)
    any_failed = any(str(t.get("status", "")).lower() == "failed" for t in traces)
    overall_status = "failed" if any_failed else "success"

    lines: list[str] = [
        f"Session: {chat_dir.name} | status={overall_status} | agents={len(traces)} "
        f"| total_iters={total_iters} | total_cost=${total_cost:.4f}",
    ]

    for t in traces:
        aid = t.get("agent_id", "unknown")
        atype = t.get("agent_type", "worker")
        parent = t.get("parent_id") or "none"
        status = t.get("status", "unknown")
        iters = t.get("iterations_used", 0)
        max_iters = t.get("max_iterations", 0)
        cost = float(t.get("total_cost_usd", 0.0))

        lines.append("")
        lines.append(
            f"## Agent {aid} ({atype}) | parent={parent} | status={status} "
            f"| iters={iters}/{max_iters} | cost=${cost:.4f}"
        )
        if t.get("instructions"):
            lines.append(f"Task: {_clip(t['instructions'], 320)}")
        if t.get("dod"):
            lines.append(f"DoD: {_clip(t['dod'], 200)}")

        events = t.get("events", []) or []
        for idx, ev in enumerate(events, start=1):
            it_num = ev.get("iteration", idx)
            llm_out = ev.get("llm_output", "") or ""
            env_res = ev.get("environment_results", "") or ""

            try:
                parsed_cmds = parse_llm_output(llm_out)
            except Exception:
                parsed_cmds = []

            if parsed_cmds:
                cmd_summaries = [_summarize_command(c) for c in parsed_cmds]
                action_str = "; ".join(cmd_summaries)
            else:
                action_str = "(no valid XML command parsed)"

            signals = _extract_signals_only(env_res)
            signal_str = f" | {' ; '.join(signals)}" if signals else ""
            lines.append(f"- Turn {it_num}: {action_str}{signal_str}")

    return "\n".join(lines)


def analyze_session(chat_id_or_path: str, user_feedback: str = "") -> dict:
    candidate_path = Path(chat_id_or_path).expanduser()
    if candidate_path.exists() and candidate_path.is_dir():
        chat_dir = candidate_path
    else:
        chat_dir = GLOBAL_ROOT / "chats" / chat_id_or_path

    log(f"\n[SwarmAnalyzer] Building curated session digest for {chat_dir}...", "info")
    session_digest = build_curated_session_digest(chat_dir)

    if not session_digest.strip():
        log("[SwarmAnalyzer] No agent traces found in session directory. Skipping.", "warning")
        return {"status": "skipped", "reason": "no_artifacts"}

    agents_md_path = (
        GLOBAL_ROOT / "AGENTS.md"
        if (GLOBAL_ROOT / "AGENTS.md").exists()
        else REPO_ROOT / "AGENTS.md"
    )
    current_agents_md = (
        agents_md_path.read_text(encoding="utf-8") if agents_md_path.exists() else ""
    )

    skills_dir = GLOBAL_ROOT / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    existing_skills = [p.stem for p in skills_dir.glob("*.md")]

    feedback_block = ""
    cleaned_feedback = (user_feedback or "").strip()
    if cleaned_feedback:
        feedback_block = (
            f"<UserFeedback>\n{cleaned_feedback}\n</UserFeedback>\n\n"
            "Pay special attention to the user's feedback above. Incorporate any durable preferences, "
            "corrections, or workflow notes into AGENTS.md or skills where appropriate, and address "
            "their feedback directly in your EvaluationReport.\n\n"
        )

    sys_prompt = load_optimizer_prompt()
    full_prompt = (
        f"{sys_prompt}\n\n"
        f"<CurrentAgentsMd>\n{current_agents_md}\n</CurrentAgentsMd>\n\n"
        f"<ExistingSkills>{', '.join(existing_skills) if existing_skills else 'None'}</ExistingSkills>\n\n"
        f"<SessionDigest>\n{session_digest}\n</SessionDigest>\n\n"
        f"{feedback_block}"
        "Analyze the curated session digest above and emit your XML optimization commands."
    )

    # Save exact input prompt for inspection and token-budget debugging
    (chat_dir / "optimizer_prompt.txt").write_text(full_prompt, encoding="utf-8")

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
            log(f"[SwarmAnalyzer] Efficiency Score: {score}", "info")
            log(f"[SwarmAnalyzer] Bottlenecks: {bottlenecks}", "warning")
            log(f"[SwarmAnalyzer] Recommendations: {recs}", "data")

        elif cmd.command == "UpdateAgentsMd":
            if isinstance(cmd.content, dict):
                new_content = cmd.content.get("Content", "").strip()
                summary = cmd.content.get("Summary", "Updated AGENTS.md")
            else:
                new_content = str(cmd.content).strip()
                summary = "Updated AGENTS.md"

            if new_content:
                (chat_dir / "AGENTS_md_backup.md").write_text(current_agents_md, encoding="utf-8")
                agents_md_path.write_text(new_content + "\n", encoding="utf-8")
                if REPO_ROOT / "AGENTS.md" != agents_md_path and (REPO_ROOT / "AGENTS.md").exists():
                    (REPO_ROOT / "AGENTS.md").write_text(new_content + "\n", encoding="utf-8")

                snapshot_prompt_history(new_content + "\n", summary, prefix="agents")
                modifications.append({
                    "type": "UpdateAgentsMd",
                    "target_file": "AGENTS.md",
                    "summary": summary,
                    "content": new_content,
                })
                log(f"[SwarmAnalyzer] Upgraded AGENTS.md: {summary}", "success")

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
                modifications.append({
                    "type": "UpsertSkill",
                    "target_file": f"skills/{skill_name}.md",
                    "summary": summary,
                    "content": skill_body,
                })
                log(f"[SwarmAnalyzer] Saved skill '{skill_path.name}': {summary}", "success")

    report_file = chat_dir / "optimizer_report.txt"
    total_cost = cost.get("total_cost", 0.0) if isinstance(cost, dict) else 0.0
    report_file.write_text(
        f"Timestamp: {datetime.now().isoformat()}\nCost: ${total_cost:.6f}\n\n{llm_output}",
        encoding="utf-8",
    )

    return {
        "status": "completed",
        "efficiency_score": str(report_summary.get("EfficiencyScore", "N/A")).strip(),
        "bottlenecks": str(report_summary.get("Bottlenecks", "")).strip(),
        "recommendations": str(report_summary.get("Recommendations", "")).strip(),
        "modifications": modifications,
        "cost_usd": total_cost,
        "user_feedback": cleaned_feedback,
        "report": report_summary,
        "cost": total_cost,
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_session(sys.argv[1])
    else:
        print("Usage: python3 -m pipelines.swarm_analyzer <chat_id_or_path>")
