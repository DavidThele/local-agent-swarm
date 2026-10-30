import subprocess
from pathlib import Path
from infrastructure.debug_colors import debug_print
from infrastructure.concurrency import TERMINAL_LOCK

def load_security_list(filepath: Path) -> set:
    """
    Parses a markdown configuration file to extract a set of commands/operators.
    Ignores headers, empty lines, descriptions, and markdown bullet points.
    """
    items = set()
    if not filepath.exists():
        debug_print(f"[Zsh] Security file not found: {filepath}", "warning")
        return items
        
    with open(filepath, 'r', encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            
            # Ignore empty lines, markdown headers, and description text
            if not line or line.startswith('#') or line.lower().startswith('this file'):
                continue
                
            # Strip markdown list syntax if the user adds bullets
            if line.startswith('- ') or line.startswith('* '):
                line = line[2:].strip()
                
            if line:
                items.add(line)
                
    return items

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    if isinstance(content, dict):
        cmd_string = content.get("Command", "").strip()
    else:
        cmd_string = str(content).strip()
    timeout = int(attributes.get("timeout", 30))
    # ... rest of zsh_exec.py remains identical
    
    if not cmd_string:
        return "[Error] No command provided."
        
    # Resolve the global workspace path
    global_root = Path.home() / ".agents"
    whitelist_path = global_root / "config" / "cmd_whitelist.md"
    blacklist_path = global_root / "config" / "cmd_blacklist.md"
    
    WHITELIST = load_security_list(whitelist_path)
    BLACKLIST = load_security_list(blacklist_path)
    
    base_cmd = cmd_string.split()[0]
    
    # Check Blacklist (Injection attempts)
    if any(char in cmd_string for char in BLACKLIST):
        with TERMINAL_LOCK: 
            approval = input(f"\n[SECURITY ALERT] Command contains blacklisted operators. Approve execution?\nCommand: {cmd_string}\n(Y/N): ")
        if approval.strip().lower() != 'y':
            return "[System] Command execution denied by user."
            
    # Check Greylist (Command not explicitly whitelisted)
    elif base_cmd not in WHITELIST:
        with TERMINAL_LOCK:
            approval = input(f"\n[SECURITY ALERT] Command '{base_cmd}' is not whitelisted. Approve execution?\nCommand: {cmd_string}\n(Y/N): ")
        if approval.strip().lower() != 'y':
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