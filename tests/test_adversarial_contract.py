import json
import queue
import threading
import pytest
from pathlib import Path

from infrastructure import parser, scrubber, prompt_router, agent_loop, concurrency, workspace
from command_executors import (
    zsh_exec,
    read_file_exec,
    write_file_exec,
    list_directory_exec,
    search_db_exec,
    question_exec,
)
from pipelines import ingestor_pipeline, log_ingestor_wrapper
from db import db_manager


# ============================================================================
# 1. PARSER ADVERSARIAL TESTS (infrastructure/parser.py)
# ============================================================================

def test_parser_handles_malformed_block_without_dropping_subsequent_valid_blocks():
    """
    Spec: If an LLM outputs one broken XML tag followed by a valid XML tag,
    parse_llm_output must skip the broken one and still return the valid one.
    """
    text = """
    <BrokenTag attr="unclosed quote>some text</BrokenTag>
    <ReadFile path="/tmp/valid.txt" />
    """
    cmds = parser.parse_llm_output(text)
    assert len(cmds) == 1
    assert cmds[0].command == "ReadFile"
    assert cmds[0].attributes["path"] == "/tmp/valid.txt"


def test_parser_handles_nested_identical_tag_names_inside_instructions():
    """
    Spec: An Orchestrator often explains how to use <SpawnAgent> inside the
    <Instructions> of a <SpawnAgent> call. The parser must not prematurely close
    the outer <SpawnAgent> at the inner </SpawnAgent>.
    """
    text = """
    <SpawnAgent type="SUB_ORCHESTRATOR">
        <Instructions>Delegate to a worker using <SpawnAgent type="WORKER">...</SpawnAgent> when ready.</Instructions>
        <Context>Repo context</Context>
        <DoD>Done</DoD>
    </SpawnAgent>
    """
    cmds = parser.parse_llm_output(text)
    assert len(cmds) == 1
    assert cmds[0].command == "SpawnAgent"
    assert cmds[0].attributes["type"] == "SUB_ORCHESTRATOR"
    assert "DoD" in cmds[0].content


def test_parser_preserves_indentation_inside_write_file_content():
    """
    Spec: Python code relies on leading indentation. Stripping leading whitespace
    from the first line of <Content> breaks indented blocks or classes.
    """
    code = "    def indented_method(self):\n        return 42"
    text = f"<WriteFile path='/tmp/a.py'><Content>\n{code}\n</Content><Summary>test</Summary></WriteFile>"
    cmds = parser.parse_llm_output(text)
    assert len(cmds) == 1
    # Check if relative indentation between line 1 and line 2 is intact
    parsed_lines = cmds[0].content["Content"].splitlines()
    assert len(parsed_lines) == 2
    assert parsed_lines[1].startswith("    ")


# ============================================================================
# 2. SHELL SECURITY & INJECTION TESTS (command_executors/zsh_exec.py)
# ============================================================================

@pytest.mark.parametrize("injected_cmd", [
    "ls\nwhoami",              # Newline command chaining bypasses split()[0] == 'ls'
    "ls $(whoami)",            # Command substitution subshell bypasses operator blacklist
    "ls `whoami`",             # Backtick subshell execution bypasses operator blacklist
])
def test_zsh_blocks_subshell_and_newline_injections_even_when_first_word_is_whitelisted(
    tmp_path, monkeypatch, injected_cmd
):
    """
    Spec: Any command attempting multi-command execution or subshell expansion
    MUST trigger the human-in-the-loop approval prompt, even if the first token ('ls')
    is in cmd_whitelist.md.
    """
    config_dir = tmp_path / ".agents" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "cmd_whitelist.md").write_text("ls\n", encoding="utf-8")
    (config_dir / "cmd_blacklist.md").write_text("|\n>\n<\n&\n;\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    prompted_user = False
    def fake_input(prompt_str):
        nonlocal prompted_user
        prompted_user = True
        return "n"

    monkeypatch.setattr("builtins.input", fake_input)
    result = zsh_exec.execute({}, {"Command": injected_cmd}, {})
    assert prompted_user, f"SECURITY BYPASS: '{injected_cmd}' executed without prompting the user!"
    assert "denied" in result.lower()


def test_zsh_timeout_enforced_on_hanging_process(tmp_path, monkeypatch):
    """
    Spec: If a command exceeds the 'timeout' attribute, zsh_exec must terminate it
    and return a timeout error message rather(than hanging the worker thread forever).
    """
    config_dir = tmp_path / ".agents" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "cmd_whitelist.md").write_text("sleep\n", encoding="utf-8")
    (config_dir / "cmd_blacklist.md").write_text("|\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: tmp_path)

    res = zsh_exec.execute({"timeout": "1"}, {"Command": "sleep 5"}, {})
    assert "timed out" in res.lower() or "[error]" in res.lower()


# ============================================================================
# 3. FILE & DIRECTORY EXECUTOR BOUNDARY TESTS
# ============================================================================

def test_read_file_inverted_or_invalid_line_ranges(tmp_path):
    """
    Spec: ReadFile should handle start_line > end_line, negative numbers,
    or non-integer line attributes gracefully without crashing.
    """
    f = tmp_path / "sample.txt"
    f.write_text("Line 1\nLine 2\nLine 3\n", encoding="utf-8")

    # Non-integer line range
    res_invalid = read_file_exec.execute({"path": str(f), "start_line": "one", "end_line": "two"}, {}, {})
    assert "[Error]" in res_invalid

    # Inverted range (start > end)
    res_inverted = read_file_exec.execute({"path": str(f), "start_line": "3", "end_line": "1"}, {}, {})
    assert isinstance(res_inverted, str)


def test_list_directory_handles_circular_symlinks_without_infinite_recursion(tmp_path):
    """
    Spec: If a directory contains a symlink pointing back to its parent directory,
    ListDirectory must not get stuck in infinite recursion.
    """
    root = tmp_path / " folder"
    root.mkdir()
    (root / "file.txt").write_text("hello", encoding="utf-8")
    loop_link = root / "self_link"
    loop_link.symlink_to(root, target_is_directory=True)

    res = list_directory_exec.execute({"path": str(root), "depth": "5"}, {}, {})
    assert "file.txt" in res


# ============================================================================
# 4. PROMPT ROUTER RESILIENCE & PRICING TESTS (infrastructure/prompt_router.py)
# ============================================================================

def test_prompt_router_retries_on_429_and_recovers_on_third_attempt(monkeypatch):
    """
    Spec: When client.models.generate_content raises a 429 APIError on attempts 1 and 2
    but succeeds on attempt 3, send_prompt must sleep, retry, and return the response
    without exiting or duplicating the user message in chat_history.
    """
    sleep_calls = []
    monkeypatch.setattr("time.sleep", lambda s: sleep_calls.append(s))

    attempts = 0
    class DummyUsage:
        prompt_token_count = 100
        candidates_token_count = 50
        thoughts_token_count = 0

    class DummyResponse:
        text = "<MarkDone><Result>OK</Result></MarkDone>"
        usage_metadata = DummyUsage()

    class FakeModels:
        def generate_content(self, model, contents):
            nonlocal attempts
            attempts += 1
            if attempts < 3:
                raise Exception("429 RESOURCE_EXHAUSTED")
            return DummyResponse()

    class FakeClient:
        def __init__(self, *args, **kwargs):
            self.models = FakeModels()

    # Patch APIError to Exception so our fake 429 is caught
    monkeypatch.setattr(prompt_router, "APIError", Exception)
    monkeypatch.setattr(prompt_router.genai, "Client", FakeClient)

    history = []
    text, updated_history, cost = prompt_router.send_prompt(
        "Hello", model=prompt_router.GEMINI_2_5_FLASH_LITE, chat_history=history, print_cost=False
    )

    assert attempts == 3
    assert sleep_calls == [10, 20]
    assert text == "<MarkDone><Result>OK</Result></MarkDone>"
    # Crucial: chat_history must have exactly 1 'user' message and 1 'model' message (not 3 duplicate 'user' messages!)
    assert len(updated_history) == 2
    assert updated_history[0].role == "user"
    assert updated_history[1].role == "model"


# ============================================================================
# 5. CONCURRENCY & CRASHING CHILD THREAD TESTS (agent_loop.py & concurrency.py)
# ============================================================================

def test_crashing_child_thread_does_not_deadlock_parent_wait_for_agents(monkeypatch):
    """
    Spec: If a spawned background child raises an unhandled RuntimeError inside run_agent,
    the parent waiting via <WaitForAgents mode="all" /> must NOT deadlock forever;
    it must receive an ERROR notification and remove the child from active_children.
    """
    def crashing_run_agent(agent_type, instructions, context, dod, chat_context_state, agent_id="main"):
        raise RuntimeError("Simulated child crash!")

    monkeypatch.setattr(agent_loop, "run_agent", crashing_run_agent)

    parent_ctx = {
        "local_chat_dir": "/tmp/chat",
        "worker_id": "main",
        "notification_queue": queue.Queue(),
        "active_children": {}
    }

    child_id = concurrency.spawn_background_agent(
        agent_type="WORKER",
        instructions="Crash immediately",
        context="",
        dod="",
        parent_context_state=parent_ctx
    )

    assert child_id in parent_ctx["active_children"]

    # Drain with block_mode='all' - must not hang!
    msg = agent_loop.drain_child_notifications(parent_ctx, block_mode="all")
    assert "STATUS: ERROR" in msg
    assert "Simulated child crash!" in msg
    assert child_id not in parent_ctx["active_children"]


def test_agent_loop_enforces_max_iterations_cap_and_returns_failed_status(monkeypatch):
    """
    Spec: If an agent outputs valid commands on every turn but never outputs <MarkDone>,
    run_agent must terminate after exactly MAX_ITERATIONS and return status='failed'.
    """
    monkeypatch.setattr(agent_loop, "load_prompt", lambda role: "SYS_PROMPT")
    call_count = 0

    def endless_llm(prompt_text, model=None, chat_history=None):
        nonlocal call_count
        call_count += 1
        return ('<WaitForAgents mode="any" />', chat_history or [], {})

    monkeypatch.setattr(agent_loop, "send_prompt", endless_llm)

    res = agent_loop.run_agent(
        agent_type="WORKER",
        instructions="Loop forever",
        context="",
        dod="Never finish",
        chat_context_state={}
    )

    assert call_count == agent_loop.MAX_ITERATIONS
    assert res["status"] == "failed"