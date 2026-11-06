"""Shared terminal colors for diagnostic output."""

import re
import threading
import os
from pathlib import Path

COLORS = {
    "info": "\033[36m",       # Cyan: normal progress and informational messages
    "system": "\033[37m",     # White: system and workspace status
    "success": "\033[32m",    # Green: completed operations
    "warning": "\033[33m",    # Yellow: warnings and retry notices
    "error": "\033[31m",      # Red: failures and errors
    "data": "\033[34m",       # Blue: database records and command output summaries
    "debug": "\033[35m",      # Magenta: verbose model and cost diagnostics
    "reset": "\033[0m",
}

_LABEL_PATTERN = re.compile(r"(?P<leading>\s*)(?P<label>\[[^\]\n]+\])(?P<message>.*)", re.DOTALL)
LOGS_DIR = Path(
    os.environ.get("AGENTS_LOG_ROOT", str(Path(__file__).resolve().parents[1] / "logs"))
).expanduser()
DEBUG_LOG_PATH = LOGS_DIR / "debug_log.log"
_DEBUG_LOG_LOCK = threading.Lock()


def debug_print(message: object, color: str = "info") -> None:
    """Print a diagnostic message with only its source label colored."""
    color_code = COLORS[color]
    text = str(message)
    match = _LABEL_PATTERN.match(text)

    if match:
        label = match.group("label")
        colored_label = f"{color_code}{label[:-1]}: {color}]{COLORS['reset']}"
        output = f"{match.group('leading')}{colored_label}{match.group('message')}"
    else:
        output = f"{color_code}[Debug: {color}]{COLORS['reset']}{text}"

    with _DEBUG_LOG_LOCK:
        try:
            DEBUG_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
            with DEBUG_LOG_PATH.open("a", encoding="utf-8") as log_file:
                log_file.write(output + "\n")
        except OSError:
            pass

    print(output)
