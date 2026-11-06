import sys
from pathlib import Path
from datetime import datetime
from infrastructure.debugging import debug_print

GLOBAL_ROOT = Path.home() / ".agents"
HISTORY_DIR = GLOBAL_ROOT / "prompts" / "agents_prompt_history"

def snapshot_prompt_history(current_content: str, summary_msg: str, prefix: str = "agents"):
    """
    Saves a timestamped copy of a markdown prompt into ~/.agents/prompts/agents_prompt_history/
    """
    HISTORY_DIR.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    
    # Create a clean filename slug from the summary message
    slug = "".join(c if c.isalnum() else "_" for c in summary_msg).strip("_")[:30]
    filename = f"{prefix}_{timestamp}_{slug}.md"
    
    snapshot_path = HISTORY_DIR / filename
    snapshot_path.write_text(current_content, encoding="utf-8")
    debug_print(f"[Analyzer] Saved prompt history snapshot: {snapshot_path}", "system")