import os

BLOCKLIST = {"Passwords", "System Settings", "Keychain Access"}
INTERVAL_SECONDS = 0.2
DATA_DIR = os.environ.get(
    "AGENTS_LOG_DIR",
    os.path.expanduser("~/.agents/logs/moniter_data"),
)

# UI Extraction limits
MAX_UI_TREE_DEPTH = 5
MAX_DOM_LENGTH = 1000
SKIP_VALUE_ROLES = {"AXTextArea", "AXScrollArea", "AXWebArea"}