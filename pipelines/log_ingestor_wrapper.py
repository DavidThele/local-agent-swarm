
import os
import json
from pathlib import Path
from infrastructure.scrubber import scrub_text
from pipelines.ingestor_pipeline import process_telemetry
from infrastructure.debug_colors import debug_print
from datetime import date

# Core Paths
LOG_DIR = Path(
    os.environ.get("AGENTS_LOG_DIR", str(Path.cwd() / "moniter_data"))
).expanduser()
STATE_FILE = Path.home() / ".agents" / "db" / "ingestion_state.json"
LINES_PER_CHUNK = 200

def load_state() -> dict:
    """Loads the ingestion tracker state."""
    if STATE_FILE.exists():
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}

def save_state(state: dict):
    """Saves the ingestion tracker state to disk."""
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, indent=4)

def process_log_file(date_str: str):
    """
    Reads a specific day's activity.log, chunks it, scrubs it, 
    and feeds it to the Ingestor pipeline.
    """
    log_path = LOG_DIR / date_str / "activity.log"
    if not log_path.exists():
        debug_print(f"[Wrapper] Log file not found: {log_path}", "error")
        return

    # Count total lines in a fast generator pass without loading into memory
    with open(log_path, "r", encoding="utf-8", errors="ignore") as f:
        total_lines = sum(1 for _ in f)

    state = load_state()
    log_key = f"{date_str}/activity.log"
    
    # Retrieve the last processed line (defaults to 0 for new files)
    start_line = state.get(log_key, 0)
    
    debug_print(f"[Wrapper] Starting ingestion for {log_key} at line {start_line} of {total_lines}", "info")

    try:
        with open(log_path, "r", encoding="utf-8") as f:
            # Skip forward to the start line without loading into memory
            for _ in range(start_line):
                next(f, None)
            
            chunk = []
            current_line = start_line
            
            for line in f:
                chunk.append(line)
                current_line += 1
                
                # When chunk limit is reached, process it
                if len(chunk) >= LINES_PER_CHUNK:
                    process_chunk(chunk, current_line, total_lines, log_key, state)
                    chunk = []  # Reset for the next batch
            
            # Process any remaining lines at the end of the file
            if chunk:
                process_chunk(chunk, current_line, total_lines, log_key, state)
                
    except Exception as e:
        debug_print(f"[Wrapper] Failed while processing {log_path}: {e}", "error")


def process_chunk(chunk: list, current_line: int, total_lines: int, log_key: str, state: dict):
    """Scrubs and processes a single text chunk, then saves state."""
    raw_text = "".join(chunk)
    
    # 1. Scrub passwords and secrets before LLM exposure
    scrubbed_text = scrub_text(raw_text)
    
    debug_print(f"\n[Wrapper] Processing lines {current_line - len(chunk)} to {current_line} of {total_lines}...", "info")
    
    # 2. Feed to the two-pass Phase 1/Phase 2 pipeline
    process_telemetry(scrubbed_text)
    
    # 3. Update persistent state ONLY after successful ingestion
    state[log_key] = current_line
    save_state(state)
    debug_print(f"[Wrapper] State saved. {log_key} is completed up to line {current_line}/{total_lines}.", "success")

    
def ingest_all_unprocessed_logs():
    """Iterates through the moniter_data directory to process all dates except today."""
    if not LOG_DIR.exists():
        debug_print(f"[Wrapper] Log directory does not exist: {LOG_DIR}", "error")
        return

    # Adjust the format string if your directories use a different format (e.g. "%Y%m%d")
    today_str = date.today().strftime("%Y-%m-%d")
    debug_print(f"[Wrapper] Starting ingestion for all unprocessed logs, skipping today's logs ({today_str}).", "info")

    for date_folder in sorted(LOG_DIR.iterdir()):
        if date_folder.is_dir():
            debug_print(f"[Wrapper] Found log folder: {date_folder.name}", "debug")
            date_str = date_folder.name
            if date_str == today_str:
                continue
            process_log_file(date_str)


if __name__ == "__main__":
    # Example: Process a specific date directly
    # process_log_file("2026-10-20")
    
    # Or, process all folders sequentially
    ingest_all_unprocessed_logs()