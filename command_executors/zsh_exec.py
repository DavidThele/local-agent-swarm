import subprocess
from pathlib import Path
from infrastructure.debug_colors import debug_print
from infrastructure.concurrency import TERMINAL_LOCK

# Hardcoded baseline shell injection vectors (newlines, carriage returns, subshells)
# that are ALWAYS checked alongside the user's config/cmd_blacklist.md
BASELINE_BLACKLIST = {"|", ">", "<", "&", ";", "`", "$(", "${", "\n", "\r"}

def load_security_list(filepath: Path) -> set:
    """
    Parses a markdown configuration file to extract a set of commands/operators.
    Ignores headers, empty lines, descriptions, and markdown bullet points.
    """
    items = set()
    if not filepath.exists():
        debug_print(f"[Zsh] Security file not found: {filepath}", "warning")
        return items

    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()

            if not line or line.startswith("#") or line.lower().startswith("this file"):
                continue

            if line.startswith("- ") or line.startswith("* "):
                line = line[2:].strip()

            if line:
                items.add(line)

    return items

def resolve_security_file(filename: str) -> Path:
    global_path = Path.home() / ".agents" / "config" / filename
    if global_path.exists():
        return global_path
    return Path(__file__).resolve().parents[1] / "config" / filename

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    if isinstance(content, dict):
        cmd_string = content.get("Command", "").strip()
    else:
        cmd_string = str(content).strip()
    try:
        timeout = int(attributes.get("timeout", 30))
    except (TypeError, ValueError):
        return "[Error] Zsh timeout must be an integer."
    if timeout <= 0:
        return "[Error] Zsh timeout must be greater than zero."

    if not cmd_string:
        return "[Error] No command provided."

    # Resolve the global workspace path
    whitelist_path = resolve_security_file("cmd_whitelist.md")
    blacklist_path = resolve_security_file("cmd_blacklist.md")

    WHITELIST = load_security_list(whitelist_path)
    BLACKLIST = load_security_list(blacklist_path) | BASELINE_BLACKLIST

    base_cmd = cmd_string.split()[0]

    # Check Blacklist (Operators, newlines, or subshell expansions)
    if any(op in cmd_string for op in BLACKLIST):
        with TERMINAL_LOCK:
            approval = input(
                f"\n[SECURITY ALERT] Command contains blacklisted operators or subshells. Approve execution?\n"
                f"Command: {cmd_string}\n(Y/N): "
            )
        if approval.strip().lower() != "y":
            return "[System] Command execution denied by user."

    # Check Greylist (Command not explicitly whitelisted)
    elif base_cmd not in WHITELIST:
        with TERMINAL_LOCK:
            approval = input(
                f"\n[SECURITY ALERT] Command '{base_cmd}' is not whitelisted. Approve execution?\n"
                f"Command: {cmd_string}\n(Y/N): "
            )
        if approval.strip().lower() != "y":
            return "[System] Command execution denied by user."

    # Execute
    try:
        result = subprocess.run(
            cmd_string,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        stdout = result.stdout.strip()
        stderr = result.stderr.strip()

        output = []
        if stdout:
            output.append(f"STDOUT:\n{stdout}")
        if stderr:
            output.append(f"STDERR:\n{stderr}")

        return "\n".join(output) if output else "[System] Command executed successfully with no output."

    except subprocess.TimeoutExpired:
        return f"[Error] Command timed out after {timeout} seconds."
    except Exception as e:
        return f"[Error] Execution failed: {str(e)}"