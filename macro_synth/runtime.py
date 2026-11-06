"""Shared runtime state and configuration for the resident macro service."""

import os
import threading
from pathlib import Path

from infrastructure.prompt_router import GEMINI_3_5_FLASH_LITE

LOG_LINES_TO_SEND = 80
DEEP_DOM_MAX_DEPTH = 10
DEEP_DOM_MAX_VALUE_LEN = 8000
MODEL_TO_USE = GEMINI_3_5_FLASH_LITE
MAX_APP_SCREENSHOTS = 8
ACTION_BUFFER_TIME_MS = 200
WIDTH = 300
HEIGHT = 200

GLOBAL_ROOT = Path.home() / ".agents"
REPO_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = Path(os.environ.get("AGENTS_LOG_ROOT", str(GLOBAL_ROOT / "logs"))).expanduser()
DATA_DIR = Path(os.environ.get("AGENTS_LOG_DIR", str(LOGS_DIR / "moniter_data"))).expanduser()
SOCKET_PATH = Path(os.environ.get("MACRO_SERVICE_SOCKET", str(Path(os.environ.get("TMPDIR", "/tmp")) / "agents-macro-synth.sock")))

SYNTHETIC_EVENT_TAG = 0x41474E54
abort_event = threading.Event()
kill_switch_stop_event = threading.Event()
abort_lock = threading.Lock()
global_event_monitor = None
