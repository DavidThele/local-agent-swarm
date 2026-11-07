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
# Event timing and delays (in milliseconds)
ACTION_BUFFER_TIME_MS = 10        # Buffer time between high-level actions
TYPING_BUFFER_TIME_MS = 2         # Delay between typed characters in type_unicode_string
KEY_PRESS_DOWN_TIME_MS = 5        # Hold time while a key is pressed down in press_single_key
KEY_PRESS_UP_TIME_MS = 10         # Delay after releasing key / interval between repeated keys in press_single_key
KEY_COMBO_DOWN_TIME_MS = 10       # Hold time while key combo is pressed down in press_key_combo
KEY_COMBO_UP_TIME_MS = 40         # Delay after releasing key combo in press_key_combo
MOUSE_CLICK_MOVE_DELAY_MS = 15    # Delay after moving mouse before clicking in click_mouse
MOUSE_CLICK_DOWN_TIME_MS = 5      # Hold time while mouse button is pressed down in click_mouse
MOUSE_CLICK_UP_TIME_MS = 10       # Delay after mouse button release / between clicks in click_mouse
MOUSE_SCROLL_MOVE_DELAY_MS = 10   # Delay after moving mouse before scrolling in scroll_mouse
MOUSE_SCROLL_DELAY_MS = 15        # Settling delay after sending scroll event in scroll_mouse
WIDTH = 300
HEIGHT = 200

GLOBAL_ROOT = Path.home() / ".agents"
REPO_ROOT = Path(__file__).resolve().parents[1]
LOGS_DIR = Path(os.environ.get("AGENTS_LOG_ROOT", str(GLOBAL_ROOT / "logs"))).expanduser()
DATA_DIR = Path(os.environ.get("AGENTS_LOG_DIR", str(LOGS_DIR / "moniter_data"))).expanduser()
SOCKET_PATH = Path(os.environ.get("MACRO_SERVICE_SOCKET", str(Path(os.environ.get("TMPDIR", "/tmp")) / "agents-macro-synth.sock")))
SCREEN_CONTEXTS_DIR = LOGS_DIR / "screen_contexts"

SYNTHETIC_EVENT_TAG = 0x41474E54
abort_event = threading.Event()
kill_switch_stop_event = threading.Event()
abort_lock = threading.Lock()
global_event_monitor = None
