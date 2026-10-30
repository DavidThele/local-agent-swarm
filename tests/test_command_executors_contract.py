from pathlib import Path
from command_executors import (
    read_file_exec,
    write_file_exec,
    list_directory_exec,
    mark_done_exec,
    zsh_exec,
    question_exec,
    wait_for_agents_exec,
)

def test_write_and_read_file_exec_and_preserve_multiple_worker_logs(tmp_path):
    chat_dir = tmp_path / "chat_logs"
    ctx = {"local_chat_dir": str(chat_dir), "worker_id": "worker_01"}
    
    file1 = tmp_path / "hello.py"
    file2 = tmp_path / "world.py"
    
    # First write by worker_01
    res1 = write_file_exec.execute(
        {"path": str(file1)},
        {"Content": "line1\nline2\nline3\nline4\n", "Summary": "Created hello.py"},
        ctx
    )
    assert "[Success]" in res1
    assert "Created hello.py" in res1
    assert "line1\nline2" not in res1  # Full content must NOT leak into return string
    
    # Second write by the SAME worker_01
    write_file_exec.execute(
        {"path": str(file2)},
        {"Content": "print('second file')\n", "Summary": "Created world.py"},
        ctx
    )
    
    # Contract: Both writes must be preserved in the worker's full and summary logs
    full_log = (chat_dir / "worker_01_full.txt").read_text(encoding="utf-8")
    summary_log = (chat_dir / "worker_01_summary.txt").read_text(encoding="utf-8")
    assert "line1" in full_log and "print('second file')" in full_log
    assert "Created hello.py" in summary_log and "Created world.py" in summary_log
    
    # Test ReadFile line range (1-indexed inclusive)
    snippet = read_file_exec.execute({"path": str(file1), "start_line": "2", "end_line": "3"}, {}, ctx)
    assert "line2\nline3" in snippet
    assert "line1" not in snippet
    assert "line4" not in snippet

def test_zsh_exec_whitelist_greylist_and_blacklist(tmp_path, monkeypatch):
    fake_home = tmp_path
    config_dir = fake_home / ".agents" / "config"
    config_dir.mkdir(parents=True)
    (config_dir / "cmd_whitelist.md").write_text("# Whitelist\npwd\necho\n", encoding="utf-8")
    (config_dir / "cmd_blacklist.md").write_text("# Blacklist\n|\n;\n>\n", encoding="utf-8")
    monkeypatch.setattr(Path, "home", lambda: fake_home)
    
    # 1. Whitelisted command runs without calling input()
    monkeypatch.setattr("builtins.input", lambda *_: (_ for _ in ()).throw(AssertionError("Should not prompt!")))
    out = zsh_exec.execute({"timeout": "5"}, {"Command": "pwd"}, {})
    assert "STDOUT:" in out
    
    # 2. Whitelisted command with BLACKLISTED operator ('|') MUST prompt user
    monkeypatch.setattr("builtins.input", lambda *_: "n")
    denied_out = zsh_exec.execute({}, {"Command": "pwd | cat"}, {})
    assert "denied" in denied_out.lower()
    
    # 3. Greylisted command ('whoami') approved by user ('y') executes
    monkeypatch.setattr("builtins.input", lambda *_: "y")
    approved_out = zsh_exec.execute({}, {"Command": "whoami"}, {})
    assert "STDOUT:" in approved_out

def test_executors_handle_raw_string_content_without_crashing():
    """
    Contract: If parser returns a string instead of a dict for content,
    executors must handle it gracefully without throwing AttributeError.
    """
    done_str = mark_done_exec.execute({}, "Completed everything directly.", {})
    assert done_str.startswith("[STATUS_DONE]")
    
    wait_str = wait_for_agents_exec.execute({"mode": "all"}, "", {})
    assert wait_str == "[WAIT_FOR_AGENTS:all]"

def test_question_exec_hardcodes_other_option(monkeypatch):
    inputs = iter(["3", "My custom path /opt/app"])
    monkeypatch.setattr("builtins.input", lambda *_: next(inputs))
    
    reply = question_exec.execute(
        {},
        {"Text": "Which folder?", "Options": {"Option": ["/path/a", "/path/b"]}},
        {"worker_id": "main"}
    )
    assert "[User Reply] My custom path /opt/app" == reply