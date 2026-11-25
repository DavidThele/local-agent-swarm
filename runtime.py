"""Centralized customizable constants, defaults, and tuning parameters across the workspace."""

import os
import threading
from pathlib import Path

from infrastructure.models import (
    GEMINI_3_5_FLASH_LITE,
    GEMINI_3_8_FLASH,
    GEMINI_4_HYDROGEN,
)

# ==============================================================================
# WORKSPACE & STORAGE PATHS
# ==============================================================================

# Root directory for global user-level agent state, prompts, skills, and DB
GLOBAL_ROOT = Path.home() / ".agents"

# Root directory of this repository
REPO_ROOT = Path(__file__).resolve().parent

# Base directory for logs and diagnostic output (override via AGENTS_LOG_ROOT)
LOGS_DIR = Path(
    os.environ.get("AGENTS_LOG_ROOT", str(GLOBAL_ROOT / "logs"))
).expanduser()

# Directory where daily telemetry/activity logs are stored (override via AGENTS_LOG_DIR)
DATA_DIR = Path(
    os.environ.get("AGENTS_LOG_DIR", str(LOGS_DIR / "moniter_data"))
).expanduser()

# Directory for persistent ChromaDB storage and backups (override via AGENTS_DB_DIR)
DB_DIR = Path(
    os.environ.get("AGENTS_DB_DIR", str(GLOBAL_ROOT / "db"))
).expanduser()

# ChromaDB collection name used for semantic memory storage
DB_COLLECTION_NAME = "semantic_memory"

# Unix socket path used to communicate with the resident MacroService daemon.
# Default to /tmp (not $TMPDIR) so launchd, Karabiner, and terminal shells all
# resolve to the exact same socket path on macOS.
MACRO_SERVICE_SOCKET = Path(
    os.environ.get(
        "MACRO_SERVICE_SOCKET",
        "/tmp/agents-macro-synth.sock",
    )
)
SOCKET_PATH = MACRO_SERVICE_SOCKET

# Lock file path used to serialize standalone HITL modal fallbacks across processes
HITL_FALLBACK_LOCK_PATH = Path("/tmp/agents-hitl-modal.lock")

# Directory where captured screen context images are saved for macro synthesis
SCREEN_CONTEXTS_DIR = LOGS_DIR / "screen_contexts"

# Directory where timestamped prompt snapshots are saved during post-mortem analysis
PROMPT_HISTORY_DIR = GLOBAL_ROOT / "prompts" / "agents_prompt_history"

# Default unified call log path for MCP tool invocations
DEFAULT_MCP_CALL_LOG_PATH = LOGS_DIR / "tool_calls_log.log"

# Directory names skipped when walking or resolving workspace files
IGNORED_DIRS: frozenset[str] = frozenset({
    ".git",
    "node_modules",
    ".venv",
    "venv",
    "__pycache__",
    ".backups",
    ".pytest_cache",
    "dist",
    "build",
    ".next",
    "chrome_profile",
    ".DS_Store",
})


# ==============================================================================
# MODEL & ROUTER DEFAULTS
# ==============================================================================

# Default routing backend ("web" for AI Studio browser automation, "api" for Vertex AI)
DEFAULT_PROMPT_ROUTER_BACKEND = os.environ.get("PROMPT_ROUTER_BACKEND", "web")

# Supported prompt router backends
VALID_PROMPT_ROUTER_BACKENDS = ("api", "web")

# Named Chrome/Google account indices for AI Studio web routing
WEB_ROUTER_USERS: dict[str, int] = {
    "subscribed": 0,
    "personal": 1,
}

# Default account/user profile index used by the web prompt router
DEFAULT_WEB_USER_INDEX = 0

# Google Cloud Vertex AI region/location for the API prompt router
VERTEX_AI_LOCATION = "global"

# Retry backoff delays (seconds) when the API prompt router hits 429 RESOURCE_EXHAUSTED
API_RATE_LIMIT_RETRY_DELAYS = (10, 20, 30)

# Chrome application paths and CDP defaults for the AI Studio web prompt router
CHROME_APP_PATH = "/Applications/Google Chrome.app"
CHROME_BINARY = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
AISTUDIO_CHROME_PROFILE = os.environ.get(
    "AISTUDIO_CHROME_PROFILE", str(Path.home() / ".agent-browser-profile")
)
AISTUDIO_CDP_PORT = int(os.environ.get("AISTUDIO_CDP_PORT", "9223"))
AISTUDIO_CDP_HOST = "localhost"
AISTUDIO_CLOSE_DELAY_SECONDS = float(
    os.environ.get("AISTUDIO_CLOSE_DELAY_SECONDS", "8.0")
)
WEB_ROUTER_RESPONSE_TIMEOUT_SECONDS = 600.0

# Default model used for macro synthesis when not overridden
MODEL_TO_USE = GEMINI_3_5_FLASH_LITE
MACRO_MODEL_TO_USE = MODEL_TO_USE

# Model used for post-execution macro screen-recording analysis
MACRO_ANALYZER_MODEL = GEMINI_3_8_FLASH

# Model used for two-phase telemetry memory ingestion
INGESTOR_MODEL = GEMINI_4_HYDROGEN

# Models used by swarm analyzer sub-agents and orchestrators
ANALYZER_SUBAGENT_MODEL = GEMINI_3_5_FLASH_LITE
ANALYZER_ORCHESTRATOR_MODEL = GEMINI_4_HYDROGEN

# Default model IDs per agent role (overridable via AGENT_MODEL_<ROLE> env vars)
AGENT_MODEL_DEFAULTS: dict[str, str] = {
    "main_orchestrator": GEMINI_4_HYDROGEN,
    "sub_orchestrator": GEMINI_4_HYDROGEN,
    "worker": GEMINI_4_HYDROGEN,
    "web_mcp": GEMINI_4_HYDROGEN,
}

# Default thinking levels per agent role (overridable via AGENT_THINKING_<ROLE> env vars)
AGENT_THINKING_LEVEL_DEFAULTS: dict[str, str] = {
    "main_orchestrator": "High",
    "sub_orchestrator": "High",
    "worker": "Medium",
    "web_mcp": "Medium",
}

# Customizable XML/MCP commands exposed to each agent role
AGENT_COMMANDS: dict[str, tuple[str, ...]] = {
    "main_orchestrator": (
        "chat_title",
        "search_db",
        "spawn_agent",
        "wait_for_agents",
        "question",
        "mark_done",
        "chrome",
        "wait_for_user",
        "read_file",
        "list_directory",
        "find_files",
        "search_code",
        "list_backups",
        "restore_backup",
        "zsh",
    ),
    "sub_orchestrator": (
        "spawn_agent",
        "wait_for_agents",
        "mark_done",
        "read_file",
        "list_directory",
        "find_files",
        "search_code",
        "list_backups",
        "restore_backup",
        "zsh",
    ),
    "worker": (
        "zsh",
        "write_file",
        "edit_file",
        "delete_file",
        "read_file",
        "list_directory",
        "find_files",
        "search_code",
        "list_backups",
        "restore_backup",
        "mark_done",
        "chrome",
        "wait_for_user",
    ),
    "web_mcp": (
        "search_db",
        "chrome",
        "read_file",
        "list_directory",
        "find_files",
        "search_code",
        "list_backups",
        "write_file",
        "edit_file",
        "delete_file",
        "restore_backup",
        "zsh",
        "question",
    ),
}


# ==============================================================================
# AGENT LOOP, CONCURRENCY & SERVER DEFAULTS
# ==============================================================================

# Maximum tool/turn iterations allowed for worker agents
MAX_WORKER_ITERATIONS = 50

# Maximum tool/turn iterations allowed for main and sub-orchestrator agents
MAX_ORCHESTRATOR_ITERATIONS = 100

# Active LLM thinking timeout per agent in seconds (override via AGENT_THINKING_TIMEOUT_SECONDS)
AGENT_THINKING_TIMEOUT_SECONDS = float(
    os.environ.get("AGENT_THINKING_TIMEOUT_SECONDS", "300")
)

# Default host and port for the Swarm GUI / FastAPI bridge server
SWARM_GUI_HOST = "127.0.0.1"
SWARM_GUI_PORT = 8765

# Default shutdown grace timeout in seconds when stopping runtime components
SHUTDOWN_TIMEOUT_SECONDS = 4.0

# Number of visible rows in the interactive Swarm CLI chat selector menu
CLI_MENU_VIEWPORT_HEIGHT = 12

# Default host and port for the MCP HTTP server CLI
DEFAULT_MCP_HOST = "127.0.0.1"
DEFAULT_MCP_PORT = 8000


# ==============================================================================
# COMMAND EXECUTORS & SECURITY LIMITS
# ==============================================================================

# Default execution timeout in seconds for Zsh commands when not specified on the tag
DEFAULT_ZSH_TIMEOUT_SECONDS = 30

# Baseline shell operators/control characters always blocked in Zsh commands
BASELINE_ZSH_BLACKLIST = {"|", ">", "<", "&", ";", "`", "$(", "${", "\n", "\r"}

# Chrome CDP port, profile directory, and launch retry count for the <Chrome> executor
CHROME_EXEC_CDP_PORT = 9222
CHROME_EXEC_PROFILE_DIR = GLOBAL_ROOT / "chrome_profile"
CHROME_EXEC_LAUNCH_MAX_ATTEMPTS = 20

# Result caps and file-size warning threshold for code/file search executors
MAX_SEARCH_RESULTS = 200
MAX_FIND_RESULTS = 500
LARGE_FILE_THRESHOLD_BYTES = 3 * 1024 * 1024  # 3 MB

# Default result limits for backup listing and semantic memory search
DEFAULT_LIST_BACKUPS_LIMIT = 20
DEFAULT_SEARCH_DB_RESULTS = 5

# Number of historical edit shifts retained per file for surgical line projection
MAX_EDIT_HISTORY_PER_FILE = 25


# ==============================================================================
# MACRO SYNTHESIS & INPUT TIMING
# ==============================================================================

# Number of recent telemetry log lines included in macro context
LOG_LINES_TO_SEND = 80

# Maximum depth traversed when capturing the deep Accessibility (AX) DOM tree
DEEP_DOM_MAX_DEPTH = 10

# Maximum string length kept per attribute/value in deep AX DOM extraction
DEEP_DOM_MAX_VALUE_LEN = 8000

# Maximum number of window screenshots captured per macro run
MAX_APP_SCREENSHOTS = 8

# Buffer delay in milliseconds between high-level macro actions
ACTION_BUFFER_TIME_MS = 10

# Delay in milliseconds between characters when typing strings
TYPING_BUFFER_TIME_MS = 2

# Key hold and release/repeat delays in milliseconds for single-key presses
KEY_PRESS_DOWN_TIME_MS = 5
KEY_PRESS_UP_TIME_MS = 10

# Key hold and release delays in milliseconds for key combinations
KEY_COMBO_DOWN_TIME_MS = 10
KEY_COMBO_UP_TIME_MS = 10

# Mouse click move, button-down hold, and inter-click delays in milliseconds
MOUSE_CLICK_MOVE_DELAY_MS = 15
MOUSE_CLICK_DOWN_TIME_MS = 5
MOUSE_CLICK_UP_TIME_MS = 10

# Mouse scroll move and settling delays in milliseconds
MOUSE_SCROLL_MOVE_DELAY_MS = 10
MOUSE_SCROLL_DELAY_MS = 15

# Default dimensions used for synthesized/grid overlays or display helpers
WIDTH = 150
HEIGHT = 200
MACRO_DEFAULT_WIDTH = WIDTH
MACRO_DEFAULT_HEIGHT = HEIGHT

# Tag value used to identify synthetically injected Quartz/input events
SYNTHETIC_EVENT_TAG = 0x41474E54

# Shared runtime synchronization primitives and monitor reference for macro execution/kill switch
abort_event = threading.Event()
kill_switch_stop_event = threading.Event()
abort_lock = threading.Lock()
global_event_monitor = None


# ==============================================================================
# HUD, MONITOR & MEMORY INGESTION SETTINGS
# ==============================================================================

# Universal UI scale factor for the floating Macro HUD and HITL modal
HUD_SCALE = 1.0

# Explicit HUD coordinates (None anchors automatically to top-right using margins)
HUD_POS_X = None
HUD_POS_Y = None
HUD_MARGIN_RIGHT = 24.0
HUD_MARGIN_TOP = 24.0

# Base unscaled canvas dimensions for the Macro HUD
BASE_CANVAS_WIDTH = 440
BASE_CANVAS_HEIGHT = 250

# Base unscaled dimensions and initial accidental-dismiss guard for the HITL modal
BASE_MODAL_WIDTH = 420
BASE_MODAL_HEIGHT = 240
INPUT_GUARD_SECONDS = 0.5

# Applications where telemetry monitoring suspends for privacy
MONITOR_BLOCKLIST = {"Passwords", "System Settings", "Keychain Access"}

# Polling interval in seconds for the background activity monitor
MONITOR_INTERVAL_SECONDS = 0.2

# Maximum depth and DOM text length when extracting UI context
MAX_UI_TREE_DEPTH = 5
MAX_DOM_LENGTH = 1000

# AX roles whose text values are skipped during UI tree capture
SKIP_VALUE_ROLES = {"AXTextArea", "AXScrollArea", "AXWebArea"}

# Rolling character buffer size used by SecretRedactor before flushing activity logs
REDACTOR_BUFFER_CHARS = 60

# Number of similar existing memory chunks retrieved per extracted chunk during ingestion
N_INGESTION_SEARCH_RESULTS = 5

# Number of lines read per batch when ingesting daily activity logs
LOG_LINES_PER_CHUNK = 200
