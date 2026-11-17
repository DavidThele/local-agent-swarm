import os
import sys
import queue
from pathlib import Path
from infrastructure.workspace import create_chat_instance
from infrastructure.agent_loop import run_agent
from infrastructure.agent_types import AgentType
from infrastructure.logging import log
from pipelines.swarm_analyzer import analyze_session

def start_swarm_session(user_prompt: str, chat_id: str = "", run_optimizer: bool | None = None) -> dict:
    """
    Initializes a local/global symlinked chat workspace, boots the Main Orchestrator,
    and optionally runs the Phase 5 Performance Analyzer post-mortem upon completion.
    """
    auto_title = (chat_id == "")
    chat_id, local_chat_dir = create_chat_instance(chat_id=chat_id)
    
    chat_context_state = {
        "chat_id": chat_id,
        "local_chat_dir": str(local_chat_dir),
        "workspace_root": str(Path.cwd().resolve()),
        "worker_id": AgentType.MAIN_ORCHESTRATOR.id_prefix,
        "notification_queue": queue.Queue(),
        "active_children": {},
        "request_chat_title": auto_title,
    }
    
    log(f"[SwarmCLI] Starting session {chat_id}", "system")
    result = run_agent(
        agent_type=AgentType.MAIN_ORCHESTRATOR,
        instructions=user_prompt,
        context=f"Active Working Directory: {local_chat_dir.parent.parent.parent}",
        dod="Fulfill the user's request completely and accurately, then call <MarkDone>.",
        chat_context_state=chat_context_state,
        agent_id="main"
    )
    
    final_chat_id = chat_context_state.get("chat_id", chat_id)
    final_chat_dir = chat_context_state.get("local_chat_dir", str(local_chat_dir))
    
    log(f"\n[SwarmCLI] Session {final_chat_id} finished with status: {result['status']}", "success")
    print(result["result"])

    # Ask interactively if run_optimizer wasn't explicitly set to True/False
    if run_optimizer is None:
        run_optimizer = input("\nRun Performance Analyzer? [y/n]: ").strip().lower() == "y"

    if run_optimizer:
        try:
            analyze_session(final_chat_dir)
        except Exception as e:
            log(f"[SwarmCLI] Optimizer post-mortem failed: {e}", "warning")

    return result

# ==========================================
# CLI Menu Implementation
# ==========================================

def get_past_chats() -> list[str]:
    """Scans the agents workspace for historical chat folders."""
    base_dir = Path.home() / ".agents" / "chats"
    if not base_dir.exists():
        base_dir = Path.cwd() / ".agents" / "chats"
        
    if not base_dir.exists():
        return []
        
    chats = []
    # Sort by most recently modified
    for d in sorted(base_dir.iterdir(), key=lambda x: x.stat().st_mtime, reverse=True):
        if d.is_dir() and d.name != "default":
            chats.append(d.name)
    return chats

def interactive_menu(options: list[str]) -> str:
    """Renders an interactive menu handling up/down cycling and styling."""
    if os.name == 'nt':
        os.system('color') # Enable ANSI escapes on Windows standard CMD

    # Cross-platform raw character fetching
    try:
        import msvcrt
        def get_key():
            key = msvcrt.getch()
            if key in (b'\x00', b'\xe0'):
                k = msvcrt.getch()
                if k == b'H': return 'UP'
                if k == b'P': return 'DOWN'
            elif key == b'\r': return 'ENTER'
            elif key == b'\x03': raise KeyboardInterrupt
            return None
    except ImportError:
        import tty, termios
        def get_key():
            fd = sys.stdin.fileno()
            old_settings = termios.tcgetattr(fd)
            try:
                tty.setraw(fd)
                ch = sys.stdin.read(1)
                if ch == '\x1b':
                    ch2 = sys.stdin.read(2)
                    if ch2 == '[A': return 'UP'
                    if ch2 == '[B': return 'DOWN'
                elif ch in ('\r', '\n'): return 'ENTER'
                elif ch == '\x03': raise KeyboardInterrupt
            finally:
                termios.tcsetattr(fd, termios.TCSADRAIN, old_settings)
            return None

    selected = 0
    viewport_start = 0
    viewport_height = 12 # Keeps 10 chats visible + new chat + separator

    sys.stdout.write('\033[?25l') # Hide cursor during menu
    try:
        while True:
            # Shift viewport if we move outside the visible window
            if selected < viewport_start:
                viewport_start = selected
            elif selected >= viewport_start + viewport_height:
                viewport_start = selected - viewport_height + 1
                
            visible_options = options[viewport_start:viewport_start + viewport_height]
            
            sys.stdout.write('\r')
            for i, opt in enumerate(visible_options):
                actual_idx = viewport_start + i
                is_selected = (actual_idx == selected)
                
                # Colors
                gray = '\033[90m'
                white = '\033[97m'
                reset = '\033[0m'
                
                if opt == "---":
                    print(f"{gray}  {opt}{reset}\033[K")
                elif is_selected:
                    print(f"{white}> {opt}{reset}\033[K")
                else:
                    print(f"{gray}  {opt}{reset}\033[K")
            
            # Reset cursor back up to redraw on the next frame
            sys.stdout.write(f"\033[{len(visible_options)}A")
            sys.stdout.flush()

            key = get_key()
            if key == 'UP':
                selected -= 1
                if selected >= 0 and options[selected] == "---":
                    selected -= 1
                if selected < 0:
                    selected = len(options) - 1 # Cycle to bottom
                    if options[selected] == "---": 
                        selected -= 1
            elif key == 'DOWN':
                selected += 1
                if selected < len(options) and options[selected] == "---":
                    selected += 1
                if selected >= len(options):
                    selected = 0 # Cycle to top
            elif key == 'ENTER':
                sys.stdout.write(f"\033[{len(visible_options)}B") # Move cursor past menu
                return options[selected]
    finally:
        sys.stdout.write('\033[?25h') # Re-enable cursor
        sys.stdout.flush()

if __name__ == "__main__":
    print("\nSelect a session to start:")
    chats = get_past_chats()
    
    menu_options = ["+ New Chat"]
    if chats:
        menu_options.append("---")
        menu_options.extend(chats)
        
    try:
        choice = interactive_menu(menu_options)
        
        chat_id_to_pass = "" if choice == "+ New Chat" else choice
        
        if choice != "+ New Chat":
            print(f"Resuming chat: {choice}\n")
            
        prompt = input("Enter task for the Agent Swarm: ").strip()
        
        if prompt:
            start_swarm_session(prompt, chat_id=chat_id_to_pass)
        else: 
            log("[SwarmCLI] No prompt provided. Exiting.", "error")
            
    except KeyboardInterrupt:
        print("\n")
        log("[SwarmCLI] Exited by user.", "system")