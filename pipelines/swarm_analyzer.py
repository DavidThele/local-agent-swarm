import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path
from infrastructure.logging import log
from infrastructure.models import GEMINI_3_5_FLASH_LITE, GEMINI_4_HYDROGEN
from infrastructure.parser import parse_llm_output
from infrastructure.prompt_router import send_prompt
from pipelines.performance_analyzer import snapshot_prompt_history

GLOBAL_ROOT = Path.home() / ".agents"
REPO_ROOT = Path(__file__).resolve().parents[1]

SUBAGENT_MODEL = GEMINI_3_5_FLASH_LITE
ORCHESTRATOR_MODEL = GEMINI_4_HYDROGEN

ALLOWED_ROLE_PROMPTS = ("main_orchestrator", "sub_orchestrator", "worker")

ANALYZER_SUBAGENTS = (
    "token_optimizer",
    "efficiency_optimizer",
    "correctness_optimizer",
    "delegation_auditor",
    "memory_skill_harvester",
    "bloat_pruner",
)

_ROLE_SORT_ORDER = {
    "main_orchestrator": 0,
    "sub_orchestrator": 1,
    "worker": 2,
}


def _resolve_prompt_path(relative_path: str) -> Path:
    global_path = GLOBAL_ROOT / relative_path
    if global_path.exists():
        return global_path
    repo_path = REPO_ROOT / relative_path
    if repo_path.exists():
        return repo_path
    raise FileNotFoundError(
        f"Prompt file not found at {global_path} or {repo_path}"
    )


def load_optimizer_prompt() -> str:
    return _resolve_prompt_path("prompts/swarm_analyzer_instructions.md").read_text(encoding="utf-8")


def load_subagent_prompt(subagent_name: str) -> str:
    return _resolve_prompt_path(f"prompts/analyzer_subagents/{subagent_name}.md").read_text(encoding="utf-8")


def _load_role_prompts() -> dict[str, tuple[Path, str]]:
    role_prompts: dict[str, tuple[Path, str]] = {}
    for role in ALLOWED_ROLE_PROMPTS:
        rel = f"prompts/{role}.md"
        global_path = GLOBAL_ROOT / rel
        repo_path = REPO_ROOT / rel
        path = global_path if global_path.exists() else repo_path
        text = path.read_text(encoding="utf-8") if path.exists() else ""
        role_prompts[role] = (path, text)
    return role_prompts


def _format_role_prompts_xml(role_prompts: dict[str, tuple[Path, str]]) -> str:
    blocks = []
    for role in ALLOWED_ROLE_PROMPTS:
        _, text = role_prompts.get(role, (None, ""))
        blocks.append(f'<RolePrompt role="{role}" chars="{len(text)}">\n{text}\n</RolePrompt>')
    return "\n\n".join(blocks)


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

    seen: set[str] = set()
    deduped: list[str] = []
    for s in signals:
        if s not in seen:
            seen.add(s)
            deduped.append(s)
        if len(deduped) >= 4:
            break
    return deduped


def _extract_error_snippets(env_results: str, max_snippets: int = 3, max_chars: int = 420) -> list[str]:
    """
    Extracts command error snippets from environment_results for the Correctness Optimizer.
    Captures the failing command block header and the error body (clipped) without dumping
    successful stdout or file reads.
    """
    if not env_results:
        return []

    text = str(env_results)
    error_markers = (
        "[Error]",
        "[System Error]",
        "DENIED",
        "[SECURITY",
        "Traceback (most recent call last)",
        "Exit Code:",
        "FAILED",
        "AssertionError",
    )

    sections = re.split(r"(?=--- Result of <[^>]+> ---)", text)
    snippets: list[str] = []
    for section in sections:
        stripped = section.strip()
        if not stripped:
            continue
        if stripped.startswith("[STATUS_DONE]"):
            continue
        has_error = any(marker in stripped for marker in error_markers)
        if has_error and "Exit Code: 0" in stripped:
            other_markers = [m for m in error_markers if m != "Exit Code:"]
            if not any(m in stripped for m in other_markers):
                has_error = False
        if has_error:
            snippets.append(_clip(stripped, max_chars))
            if len(snippets) >= max_snippets:
                break
    return snippets


def _extract_markdone_result(trace: dict) -> tuple[str, str]:
    """
    Extracts the final <MarkDone> Result and Summary from an agent's trace events
    (without reading *_summary.txt).
    """
    events = trace.get("events", []) or []
    for ev in reversed(events):
        llm_out = ev.get("llm_output", "") or ""
        try:
            cmds = parse_llm_output(llm_out)
        except Exception:
            cmds = []
        for cmd in reversed(cmds):
            if cmd.command == "MarkDone":
                if isinstance(cmd.content, dict):
                    res = str(cmd.content.get("Result", "") or "").strip()
                    summ = str(cmd.content.get("Summary", "") or "").strip()
                    return res, summ
                return str(cmd.content or "").strip(), ""
    return "", ""


def _load_session_traces(chat_dir: Path) -> list[dict]:
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

    traces.sort(
        key=lambda t: (
            _ROLE_SORT_ORDER.get(str(t.get("agent_type", "worker")), 2),
            str(t.get("agent_id", "")),
        )
    )
    return traces


def _build_session_header(chat_dir: Path, traces: list[dict]) -> str:
    total_iters = sum(int(t.get("iterations_used", 0)) for t in traces)
    total_cost = sum(float(t.get("total_cost_usd", 0.0)) for t in traces)
    any_failed = any(str(t.get("status", "")).lower() == "failed" for t in traces)
    overall_status = "failed" if any_failed else "success"
    total_tokens = sum(
        int(ev.get("total_tokens", 0) or 0)
        for t in traces
        for ev in (t.get("events", []) or [])
    )
    token_part = f" | total_tokens={total_tokens:,}" if total_tokens else ""
    return (
        f"Session: {chat_dir.name} | status={overall_status} | agents={len(traces)} "
        f"| total_iters={total_iters} | total_cost=${total_cost:.4f}{token_part}"
    )


def _format_session_digest(
    chat_dir: Path,
    traces: list[dict],
    *,
    include_token_stats: bool = False,
    include_correctness_details: bool = False,
) -> str:
    if not traces:
        return ""

    lines: list[str] = [_build_session_header(chat_dir, traces)]

    for t in traces:
        aid = t.get("agent_id", "unknown")
        atype = t.get("agent_type", "worker")
        parent = t.get("parent_id") or "none"
        status = t.get("status", "unknown")
        iters = t.get("iterations_used", 0)
        max_iters = t.get("max_iterations", 0)
        cost = float(t.get("total_cost_usd", 0.0))

        events = t.get("events", []) or []
        agent_header = (
            f"## Agent {aid} ({atype}) | parent={parent} | status={status} "
            f"| iters={iters}/{max_iters} | cost=${cost:.4f}"
        )
        if include_token_stats:
            a_in = sum(int(ev.get("input_tokens", 0) or 0) for ev in events)
            a_out = sum(int(ev.get("output_tokens", 0) or 0) for ev in events)
            a_think = sum(int(ev.get("thinking_tokens", 0) or 0) for ev in events)
            if a_in or a_out or a_think:
                agent_header += f" | tokens(in={a_in:,}, out={a_out:,}, think={a_think:,})"

        lines.append("")
        lines.append(agent_header)
        if t.get("instructions"):
            lines.append(f"Task: {_clip(t['instructions'], 320)}")
        if t.get("dod"):
            lines.append(f"DoD: {_clip(t['dod'], 240)}")

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

            parts = [f"- Turn {it_num}: {action_str}"]

            if include_token_stats:
                in_tok = int(ev.get("input_tokens", 0) or 0)
                out_tok = int(ev.get("output_tokens", 0) or 0)
                think_tok = int(ev.get("thinking_tokens", 0) or 0)
                turn_cost = float(ev.get("turn_cost_usd", 0.0) or 0.0)
                prompt_chars = int(ev.get("prompt_chars", 0) or 0)
                out_chars = int(ev.get("llm_output_chars", len(llm_out)) or len(llm_out))
                env_chars = int(ev.get("env_results_chars", len(env_res)) or len(env_res))

                metrics_bits = []
                if in_tok or out_tok or think_tok:
                    metrics_bits.append(f"tok(in={in_tok:,}, out={out_tok:,}, think={think_tok:,})")
                if turn_cost:
                    metrics_bits.append(f"cost=${turn_cost:.5f}")
                size_bits = []
                if prompt_chars:
                    size_bits.append(f"prompt={prompt_chars:,}c")
                size_bits.append(f"out={out_chars:,}c")
                size_bits.append(f"env={env_chars:,}c")
                metrics_bits.append("size(" + ", ".join(size_bits) + ")")
                parts.append("[" + " | ".join(metrics_bits) + "]")

            if include_correctness_details:
                err_snippets = _extract_error_snippets(env_res)
                if err_snippets:
                    parts.append("ERRORS: " + " || ".join(err_snippets))
                else:
                    signals = _extract_signals_only(env_res)
                    if signals:
                        parts.append(" ; ".join(signals))
            else:
                signals = _extract_signals_only(env_res)
                if signals:
                    parts.append(" ; ".join(signals))

            lines.append(" | ".join(parts))

        if include_correctness_details:
            md_result, md_summary = _extract_markdone_result(t)
            if md_result or md_summary:
                if md_result:
                    lines.append(f"Final MarkDone Result: {_clip(md_result, 1200)}")
                if md_summary:
                    lines.append(f"Final MarkDone Summary: {_clip(md_summary, 400)}")

    return "\n".join(lines)


def build_curated_session_digest(chat_dir: Path) -> str:
    """
    Builds an ultra-concise, curated digest of a swarm session for the analyzer.
    Excludes raw trace JSONs, global_trace.json, *_summary.txt, command outputs,
    and WriteFile contents.
    """
    traces = _load_session_traces(chat_dir)
    return _format_session_digest(chat_dir, traces)


def _extract_subagent_report_fields(subagent_name: str, raw_output: str) -> dict:
    commands = parse_llm_output(raw_output)
    for cmd in commands:
        if cmd.command == "SubagentReport" and isinstance(cmd.content, dict):
            return {
                "agent": subagent_name,
                "findings": str(cmd.content.get("Findings", "")).strip(),
                "proposals": str(cmd.content.get("Proposals", "")).strip(),
                "rationale": str(cmd.content.get("Rationale", "")).strip(),
                "raw": raw_output,
            }
    return {
        "agent": subagent_name,
        "findings": _clip(raw_output, 1500),
        "proposals": "",
        "rationale": "",
        "raw": raw_output,
    }


def _run_subagent(subagent_name: str, prompt_text: str) -> dict:
    log(f"[SwarmAnalyzer] Running subagent '{subagent_name}' ({SUBAGENT_MODEL})...", "info")
    try:
        llm_output, _, cost = send_prompt(prompt_text=prompt_text, model=SUBAGENT_MODEL)
        sub_cost = float(cost.get("total_cost", 0.0)) if isinstance(cost, dict) else 0.0
        parsed = _extract_subagent_report_fields(subagent_name, llm_output)
        parsed["cost_usd"] = round(sub_cost, 6)
        parsed["model"] = SUBAGENT_MODEL
        parsed["status"] = "completed"
        return parsed
    except Exception as exc:
        log(f"[SwarmAnalyzer] Subagent '{subagent_name}' failed: {exc}", "warning")
        return {
            "agent": subagent_name,
            "status": "failed",
            "error": str(exc),
            "findings": f"Subagent failed: {exc}",
            "proposals": "None",
            "rationale": "",
            "raw": "",
            "cost_usd": 0.0,
            "model": SUBAGENT_MODEL,
        }


def _build_subagent_prompts(
    *,
    session_header: str,
    base_digest: str,
    token_digest: str,
    correctness_digest: str,
    current_agents_md: str,
    role_prompts_xml: str,
    existing_skills: list[str],
    cleaned_feedback: str,
) -> dict[str, str]:
    skills_str = ", ".join(existing_skills) if existing_skills else "None"
    feedback_xml = (
        f"<UserFeedback>\n{cleaned_feedback}\n</UserFeedback>\n\n"
        if cleaned_feedback
        else ""
    )

    prompts: dict[str, str] = {}
    for name in ANALYZER_SUBAGENTS:
        sys_prompt = load_subagent_prompt(name)
        if name == "token_optimizer":
            body = (
                f"<CurrentAgentsMd chars=\"{len(current_agents_md)}\">\n{current_agents_md}\n</CurrentAgentsMd>\n\n"
                f"<CurrentRolePrompts>\n{role_prompts_xml}\n</CurrentRolePrompts>\n\n"
                f"<SessionDigest>\n{token_digest}\n</SessionDigest>\n\n"
                f"{feedback_xml}"
            )
        elif name == "correctness_optimizer":
            body = (
                f"<CurrentAgentsMd>\n{current_agents_md}\n</CurrentAgentsMd>\n\n"
                f"<SessionDigest>\n{correctness_digest}\n</SessionDigest>\n\n"
                f"{feedback_xml}"
            )
        elif name == "bloat_pruner":
            body = (
                f"<SessionSummary>{session_header}</SessionSummary>\n\n"
                f"<CurrentAgentsMd chars=\"{len(current_agents_md)}\">\n{current_agents_md}\n</CurrentAgentsMd>\n\n"
                f"<CurrentRolePrompts>\n{role_prompts_xml}\n</CurrentRolePrompts>\n\n"
                f"<ExistingSkills>{skills_str}</ExistingSkills>\n\n"
            )
        elif name == "memory_skill_harvester":
            body = (
                f"<CurrentAgentsMd>\n{current_agents_md}\n</CurrentAgentsMd>\n\n"
                f"<ExistingSkills>{skills_str}</ExistingSkills>\n\n"
                f"<SessionDigest>\n{base_digest}\n</SessionDigest>\n\n"
                f"{feedback_xml}"
            )
        else:
            body = (
                f"<CurrentAgentsMd>\n{current_agents_md}\n</CurrentAgentsMd>\n\n"
                f"<CurrentRolePrompts>\n{role_prompts_xml}\n</CurrentRolePrompts>\n\n"
                f"<SessionDigest>\n{base_digest}\n</SessionDigest>\n\n"
                f"{feedback_xml}"
            )

        prompts[name] = (
            f"{sys_prompt}\n\n{body}"
            f"Analyze the input above and emit your <SubagentReport agent=\"{name}\"> XML block."
        )
    return prompts


def _format_subagent_feedback_xml(subagent_reports: dict[str, dict]) -> str:
    blocks = []
    for name in ANALYZER_SUBAGENTS:
        rep = subagent_reports.get(name, {})
        findings = rep.get("findings") or "None"
        proposals = rep.get("proposals") or "None"
        rationale = rep.get("rationale") or "None"
        blocks.append(
            f'<SubagentReport agent="{name}">\n'
            f"    <Findings>{findings}</Findings>\n"
            f"    <Proposals>{proposals}</Proposals>\n"
            f"    <Rationale>{rationale}</Rationale>\n"
            f"</SubagentReport>"
        )
    return "\n\n".join(blocks)


def analyze_session(chat_id_or_path: str, user_feedback: str = "") -> dict:
    candidate_path = Path(chat_id_or_path).expanduser()
    if candidate_path.exists() and candidate_path.is_dir():
        chat_dir = candidate_path
    else:
        chat_dir = GLOBAL_ROOT / "chats" / chat_id_or_path

    log(f"\n[SwarmAnalyzer] Loading traces and building specialized digests for {chat_dir}...", "info")
    traces = _load_session_traces(chat_dir)
    if not traces:
        log("[SwarmAnalyzer] No agent traces found in session directory. Skipping.", "warning")
        return {"status": "skipped", "reason": "no_artifacts"}

    session_header = _build_session_header(chat_dir, traces)
    base_digest = _format_session_digest(chat_dir, traces)
    token_digest = _format_session_digest(chat_dir, traces, include_token_stats=True)
    correctness_digest = _format_session_digest(chat_dir, traces, include_correctness_details=True)

    agents_md_path = (
        GLOBAL_ROOT / "AGENTS.md"
        if (GLOBAL_ROOT / "AGENTS.md").exists()
        else REPO_ROOT / "AGENTS.md"
    )
    current_agents_md = (
        agents_md_path.read_text(encoding="utf-8") if agents_md_path.exists() else ""
    )

    role_prompts = _load_role_prompts()
    role_prompts_xml = _format_role_prompts_xml(role_prompts)

    skills_dir = GLOBAL_ROOT / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)
    existing_skills = sorted(p.stem for p in skills_dir.glob("*.md"))

    cleaned_feedback = (user_feedback or "").strip()

    # 1. Run all specialist subagents in parallel on GEMINI_3_5_FLASH_LITE
    subagent_prompts = _build_subagent_prompts(
        session_header=session_header,
        base_digest=base_digest,
        token_digest=token_digest,
        correctness_digest=correctness_digest,
        current_agents_md=current_agents_md,
        role_prompts_xml=role_prompts_xml,
        existing_skills=existing_skills,
        cleaned_feedback=cleaned_feedback,
    )

    subagent_reports: dict[str, dict] = {}
    with ThreadPoolExecutor(max_workers=len(ANALYZER_SUBAGENTS)) as pool:
        future_map = {
            pool.submit(_run_subagent, name, prompt): name
            for name, prompt in subagent_prompts.items()
        }
        for future in as_completed(future_map):
            name = future_map[future]
            subagent_reports[name] = future.result()

    subagents_total_cost = sum(
        float(rep.get("cost_usd", 0.0)) for rep in subagent_reports.values()
    )

    (chat_dir / "optimizer_subagents_report.json").write_text(
        json.dumps(
            {
                "timestamp": datetime.now().isoformat(),
                "subagent_model": SUBAGENT_MODEL,
                "total_subagents_cost_usd": round(subagents_total_cost, 6),
                "reports": subagent_reports,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    # 2. Feed all subagent reports into the Analyzer Orchestrator on GEMINI_4_HYDROGEN
    feedback_block = ""
    if cleaned_feedback:
        feedback_block = (
            f"<UserFeedback>\n{cleaned_feedback}\n</UserFeedback>\n\n"
            "Pay special attention to the user's feedback above. Incorporate durable preferences, "
            "corrections, or workflow notes into AGENTS.md, role prompts, or skills where appropriate, "
            "and address their feedback directly in your EvaluationReport.\n\n"
        )

    orchestrator_sys_prompt = load_optimizer_prompt()
    subagent_feedback_xml = _format_subagent_feedback_xml(subagent_reports)

    full_prompt = (
        f"{orchestrator_sys_prompt}\n\n"
        f"<SessionSummary>{session_header}</SessionSummary>\n\n"
        f"<CurrentAgentsMd chars=\"{len(current_agents_md)}\">\n{current_agents_md}\n</CurrentAgentsMd>\n\n"
        f"<CurrentRolePrompts>\n{role_prompts_xml}\n</CurrentRolePrompts>\n\n"
        f"<ExistingSkills>{', '.join(existing_skills) if existing_skills else 'None'}</ExistingSkills>\n\n"
        f"<SubagentFeedback>\n{subagent_feedback_xml}\n</SubagentFeedback>\n\n"
        f"{feedback_block}"
        "Evaluate every subagent proposal above using the token-cost vs. efficiency/correctness balance, "
        "and emit your XML optimization commands."
    )

    (chat_dir / "optimizer_prompt.txt").write_text(full_prompt, encoding="utf-8")

    log(f"[SwarmAnalyzer] Running Analyzer Orchestrator ({ORCHESTRATOR_MODEL})...", "info")
    llm_output, _, orch_cost_info = send_prompt(prompt_text=full_prompt, model=ORCHESTRATOR_MODEL)
    orchestrator_cost = (
        float(orch_cost_info.get("total_cost", 0.0))
        if isinstance(orch_cost_info, dict)
        else 0.0
    )
    commands = parse_llm_output(llm_output)

    report_summary: dict = {}
    modifications: list[dict] = []

    for cmd in commands:
        if cmd.command == "EvaluationReport" and isinstance(cmd.content, dict):
            report_summary = cmd.content
            score = report_summary.get("EfficiencyScore", "N/A")
            bottlenecks = report_summary.get("Bottlenecks", "None")
            recs = report_summary.get("Recommendations", "None")
            decisions = report_summary.get("Decisions", "")
            log(f"[SwarmAnalyzer] Efficiency Score: {score}", "info")
            log(f"[SwarmAnalyzer] Bottlenecks: {bottlenecks}", "warning")
            log(f"[SwarmAnalyzer] Recommendations: {recs}", "data")
            if decisions:
                log(f"[SwarmAnalyzer] Orchestrator Decisions:\n{decisions}", "data")

        elif cmd.command == "UpdateAgentsMd":
            if isinstance(cmd.content, dict):
                new_content = str(cmd.content.get("Content", "")).strip()
                summary = str(cmd.content.get("Summary", "Updated AGENTS.md")).strip()
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

        elif cmd.command == "UpdateRolePrompt":
            role_name = str(cmd.attributes.get("role", "")).strip().lower()
            if role_name not in ALLOWED_ROLE_PROMPTS:
                log(
                    f"[SwarmAnalyzer] Rejected UpdateRolePrompt for disallowed target '{role_name}'.",
                    "warning",
                )
                continue

            if isinstance(cmd.content, dict):
                new_content = str(cmd.content.get("Content", "")).strip()
                summary = str(cmd.content.get("Summary", f"Updated prompts/{role_name}.md")).strip()
            else:
                new_content = str(cmd.content).strip()
                summary = f"Updated prompts/{role_name}.md"

            if new_content:
                target_path, old_text = role_prompts[role_name]
                (chat_dir / f"{role_name}_prompt_backup.md").write_text(old_text, encoding="utf-8")
                target_path.parent.mkdir(parents=True, exist_ok=True)
                target_path.write_text(new_content + "\n", encoding="utf-8")

                repo_role_path = REPO_ROOT / "prompts" / f"{role_name}.md"
                if repo_role_path != target_path and repo_role_path.exists():
                    repo_role_path.write_text(new_content + "\n", encoding="utf-8")

                snapshot_prompt_history(new_content + "\n", summary, prefix=f"role_{role_name}")
                modifications.append({
                    "type": "UpdateRolePrompt",
                    "target_file": f"prompts/{role_name}.md",
                    "summary": summary,
                    "content": new_content,
                })
                log(f"[SwarmAnalyzer] Upgraded prompts/{role_name}.md: {summary}", "success")

        elif cmd.command == "UpsertSkill":
            skill_name = cmd.attributes.get("name", "").strip().lower().replace(" ", "_")
            if isinstance(cmd.content, dict):
                skill_body = str(cmd.content.get("Content", "")).strip()
                summary = str(cmd.content.get("Summary", f"Upserted skill {skill_name}")).strip()
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

    total_cost = subagents_total_cost + orchestrator_cost
    cost_breakdown = {
        "subagents_cost_usd": round(subagents_total_cost, 6),
        "orchestrator_cost_usd": round(orchestrator_cost, 6),
        "total_cost_usd": round(total_cost, 6),
        "per_subagent_cost_usd": {
            name: round(float(rep.get("cost_usd", 0.0)), 6)
            for name, rep in subagent_reports.items()
        },
    }

    report_file = chat_dir / "optimizer_report.txt"
    report_file.write_text(
        f"Timestamp: {datetime.now().isoformat()}\n"
        f"Subagent Model: {SUBAGENT_MODEL} (Cost: ${subagents_total_cost:.6f})\n"
        f"Orchestrator Model: {ORCHESTRATOR_MODEL} (Cost: ${orchestrator_cost:.6f})\n"
        f"Total Cost: ${total_cost:.6f}\n\n"
        f"{llm_output}",
        encoding="utf-8",
    )

    return {
        "status": "completed",
        "efficiency_score": str(report_summary.get("EfficiencyScore", "N/A")).strip(),
        "bottlenecks": str(report_summary.get("Bottlenecks", "")).strip(),
        "recommendations": str(report_summary.get("Recommendations", "")).strip(),
        "decisions": str(report_summary.get("Decisions", "")).strip(),
        "modifications": modifications,
        "cost_usd": total_cost,
        "cost_breakdown": cost_breakdown,
        "subagent_reports": subagent_reports,
        "user_feedback": cleaned_feedback,
        "report": report_summary,
        "cost": total_cost,
    }


if __name__ == "__main__":
    if len(sys.argv) > 1:
        analyze_session(sys.argv[1])
    else:
        print("Usage: python3 -m pipelines.swarm_analyzer <chat_id_or_path>")
