# local-agent-swarm

A local-first, macOS-native autonomous agent swarm, Streamable HTTP MCP server, and OS-level macro synthesizer. It combines a hierarchical multi-agent execution engine, a persistent semantic memory store (ChromaDB), a unified command and backup layer shared between swarm agents and remote MCP clients, a resident Programming-by-Demonstration macro service with floating WebKit HUD modals, and a multi-subagent post-mortem optimizer.

---

## Defining Features

- **Hierarchical Async Delegation (XML Protocol):** A 3-tier swarm (`Main Orchestrator` -> `Sub-Orchestrator` -> `Worker`) where orchestrators spawn background daemon threads via `<SpawnAgent>` and synchronize with `<WaitForAgents mode="any|all" />`. Custom XML parsing with automatic CDATA wrapping prevents raw code and shell operators from breaking tool calls. Includes cascading node cancellation and per-agent active LLM thinking timeouts (`AGENT_THINKING_TIMEOUT_SECONDS`).
- **Streamable HTTP MCP Server (`mcp_server/` + `mcp_command_adapters/`):** Exposes the same underlying `command_executors/` to remote AI clients over Streamable HTTP (`/mcp`) with OAuth 2.1 (`authorization_code` + PKCE, `client_credentials`, `refresh_token`, and optional static Bearer token). Tool permissions are controlled by `AgentType.WEB_MCP` in `runtime.py`, with `--read-only` filtering, unified call logging (`logs/tool_calls_log.log`), concise terminal summaries, and multimodal `chrome` responses (DOM + PNG screenshot).
- **Unified Command & Session-Organized Backup Layer:** `list_directory` is the canonical directory tree command (with file sizes, line counts, binary detection, and >3 MB warnings). `write_file` handles full-file create/overwrite while `edit_file` performs surgical search-and-replace with automatic stale line-range shift projection. Every tracked file mutation (`write_file`, `edit_file`, `delete_file`) across both swarm workers and MCP automatically saves a unified `.diff` backup under `.backups/<session_id>/` (skipping `.gitignore`d files and blocking direct writes to `.backups/` or `.env`), revertible via `restore_backup`.
- **Universal Upper-Right macOS HUD Modal (`HitlModalHUD`):** Interactive `question` prompts and `Security` approvals (`zsh` greylist and out-of-workspace file access) surface in an upper-right floating WebKit panel matching the Macro HUD theme. Features a 0.5s accidental-input guard, `Cmd+1`..`Cmd+9` option shortcuts, auto-focused "Other" free-text input, `Esc` dismissal, auto-expanding height with scrolling, FIFO queuing with batched reply release in the resident `MacroService`, automatic subprocess fallback + macOS notification if `MacroService` is stopped, and bi-directional sync with `swarm_gui.py`.
- **Resident OS-Level Macro Synthesizer (Programming by Demonstration):** A background macOS service (`macro_service`) that reads recent telemetry, clipboard, Accessibility (AX) DOM trees, and grid-overlaid window screenshots to finish repetitive workflows via Quartz keyboard/mouse events. Includes a floating WebKit HUD, on-device Apple Speech Recognition, an `Esc`/`Fn` physical kill switch, and a video-based `macro_analyzer` that watches recordings of its own runs to refine `macro_instructions.md`.
- **Multi-Subagent Self-Improving Optimizer:** After a session finishes, `swarm_analyzer` runs specialized sub-agents (`bloat_pruner`, `correctness_optimizer`, `delegation_auditor`, `efficiency_optimizer`, `memory_skill_harvester`, `token_optimizer`) across every agent's JSON execution trace (`*_trace.json`) to upgrade `~/.agents/AGENTS.md`, role prompts, and reusable workflows in `~/.agents/skills/`.
- **Privacy-First Local Telemetry & Semantic Memory:** A background activity monitor logs app switches, compact AX UI trees, and inputs while automatically suspending inside `Passwords`, `System Settings`, `Keychain Access`, or any `AXSecureTextField`. A rolling `SecretRedactor` and regex scrubber strip API keys, JWTs, SSNs, and credit cards before writing to disk or calling an LLM.
- **Zero-Shell Security Sandbox:** `<Zsh>` / `zsh` runs with `shell=False` and rejects pipes, redirects, and subshells. Whitelisted read-only utilities execute silently; everything else pauses for Human-in-the-Loop (HITL) approval. File reads/writes outside the active workspace root also require explicit approval with a diff preview.
- **Dual Prompt Routing & Live Cost Tracking:** `infrastructure/prompt_router.py` supports both Vertex AI (`api`) and isolated Chrome CDP AI Studio (`web`) backends, logging per-turn token and USD costs to session traces.
- **Native macOS Command Center UI:** An optional PyObjC/WKWebView desktop app (`swarm_gui.py`) powered by FastAPI, WebSockets, and React Flow. Visualizes the live agent DAG, streams command logs, syncs HITL approvals with the upper-right HUD modal, and features an animated sprite mascot ("Byte").

---

## Project Layout

```text
.
├── runtime.py                  # Centralized paths, models, role permissions, HUD & timing config
├── swarm_cli.py                # Interactive terminal entrypoint for the agent swarm
├── swarm_gui.py                # Native macOS PyObjC/WKWebView Command Center UI
├── swarm_server.py             # FastAPI + WebSocket backend for swarm_gui
├── infrastructure/             # Agent loop, parser, routers, concurrency, backups, diff engine, HUD client, UI bridge
├── commands/                   # XML command documentation injected into swarm agent prompts
├── command_executors/          # Shared command implementations (files, search, backups, zsh, chrome, search_db, question, etc.)
├── mcp_server/                 # Streamable HTTP MCP server, OAuth 2.1 middleware, CLI, tool-call logger
├── mcp_command_adapters/       # Typed MCP tool adapters wrapping command_executors/
├── macro_synth/                # Resident macro service, Quartz input runner, context capture, MacroHUD & HitlModalHUD
├── pipelines/                  # Activity monitor, semantic memory ingestor, multi-subagent swarm analyzer
├── db/                         # ChromaDB semantic memory manager & ingestion state
├── prompts/                    # Role prompts, macro instructions, and analyzer sub-agent prompts
├── config/                     # cmd_whitelist.md and cmd_blacklist.md
├── swarm-widget-ui/            # React + TypeScript + Tailwind frontend for swarm_gui
├── launchd/                    # macOS LaunchAgent plist for resident MacroService
└── tests/                      # Pytest suite (cancellation/timeouts, graceful shutdown, MCP/backups/HUD queue)
```

---

## Installation

### 1. Prerequisites
- **macOS** (required for PyObjC, Quartz, Accessibility APIs, WebKit HUD, and native speech recognition)
- **Python 3.11 - 3.13** managed via [`uv`](https://docs.astral.sh/uv/)
- **Node.js 18+** (only required if building or developing the `swarm-widget-ui` frontend)
- **Google Cloud / Vertex AI** project with Gemini API access (or a Chrome profile signed into AI Studio for `web` routing)

### 2. Install Python Dependencies
```bash
git clone <your-repo-url> local-agent-swarm
cd local-agent-swarm
uv sync
```

This creates `.venv`, installs the project in editable mode, and syncs all locked dependencies (`chromadb`, `google-genai`, `mcp`, `fastapi`, `starlette`, `uvicorn`, `playwright`, `pynput`, and PyObjC frameworks).

### 3. Build the Desktop UI (Optional)
If you plan to use the native macOS GUI (`swarm_gui.py`):

```bash
cd swarm-widget-ui
npm install
npm run build
cd ..
```

### 4. Grant macOS Permissions
For the macro synthesizer, activity monitor, and voice input to work, grant the following permissions in **System Settings -> Privacy & Security** to your terminal app (e.g., iTerm2) and/or `.venv/bin/python`:
- **Accessibility** (required for AX DOM inspection, `pynput`, and Quartz synthetic input)
- **Input Monitoring** (required for the activity monitor and physical kill switch)
- **Screen & System Audio Recording** (required for window screenshots and macro screen recordings)
- **Microphone & Speech Recognition** (required for voice prompts in the macro HUD)

---

## Configuration

### Centralized Config (`runtime.py`)
All customizable constants, paths, model assignments, role command permissions (`AGENT_COMMANDS`), HUD layout/scaling (`HUD_SCALE`, `HUD_MARGIN_RIGHT`, `HUD_MARGIN_TOP`, `INPUT_GUARD_SECONDS`), macro input timings, and monitor/ingestion limits live in root `runtime.py`.

### Credentials & Environment Variables
For Vertex AI routing (`PROMPT_ROUTER_BACKEND="api"`), authenticate with Application Default Credentials:

```bash
gcloud auth application-default login
```

Create a `.env` file in the repository root (or export these in your shell):

```bash
# Required for Vertex AI routing
GOOGLE_CLOUD_PROJECT="your-gcp-project-id"

# Prompt router backend: "web" (AI Studio CDP) or "api" (Vertex AI)
PROMPT_ROUTER_BACKEND="web"

# Optional MCP OAuth credentials (auto-generated on first `mcp_server` run if omitted)
MCP_CLIENT_ID="mcp_..."
MCP_CLIENT_SECRET="..."
# Optional static Bearer token for non-OAuth MCP clients
# MCP_AUTH_TOKEN="..."

# Optional path & runtime overrides (defaults shown)
AGENTS_DB_DIR="$HOME/.agents/db"
AGENTS_LOG_ROOT="$HOME/.agents/logs"
AGENTS_LOG_DIR="$HOME/.agents/logs/moniter_data"
MACRO_SERVICE_SOCKET="/tmp/agents-macro-synth.sock"
AGENT_THINKING_TIMEOUT_SECONDS="300"

# Optional per-role model & thinking overrides
# AGENT_MODEL_MAIN_ORCHESTRATOR / AGENT_THINKING_MAIN_ORCHESTRATOR
# AGENT_MODEL_SUB_ORCHESTRATOR  / AGENT_THINKING_SUB_ORCHESTRATOR
# AGENT_MODEL_WORKER            / AGENT_THINKING_WORKER
# AGENT_MODEL_WEB_MCP           / AGENT_THINKING_WEB_MCP
```

### Global Workspace (`~/.agents`)
On first run, the swarm initializes `~/.agents` to share state across all projects:
- `~/.agents/AGENTS.md`: Global user profile, paths, and rules (dynamically updated by the optimizer).
- `~/.agents/config/`: Custom `cmd_whitelist.md` and `cmd_blacklist.md` (overrides repo `config/`).
- `~/.agents/prompts/`: Custom role prompts and `macro_instructions.md` (overrides repo `prompts/`).
- `~/.agents/prompts/agents_prompt_history/`: Timestamped snapshots of automated prompt upgrades.
- `~/.agents/skills/`: Reusable `.md` workflow skills generated by `swarm_analyzer`.
- `~/.agents/chats/`: Symlinks to every project's local `.agents/chats/<chat_id>/` directory.
- `~/.agents/db/`: Persistent ChromaDB vector store, `ingestion_state.json`, and automatic `backups/`.

### Security Lists & Role Permissions
- **Shell allowlist/blacklist:** Edit `config/cmd_whitelist.md` (or `~/.agents/config/cmd_whitelist.md`) to control which read-only commands execute without prompting. Shell operators (`|`, `>`, `<`, `&`, `;`, `` ` ``, `$(`, `${`, newlines) are always blocked by `cmd_blacklist.md` and `BASELINE_ZSH_BLACKLIST`.
- **Per-role command grants:** Edit `AGENT_COMMANDS` in `runtime.py` to customize which commands are exposed to `main_orchestrator`, `sub_orchestrator`, `worker`, and `web_mcp`.

---

## Running the Swarm

### Interactive CLI
Run from any project directory (the current working directory becomes the authorized workspace root):

```bash
uv run swarm_cli.py
```

Use the arrow-key menu to start a new chat or resume a previous session. When the swarm completes, you will be prompted to optionally run the Performance Analyzer.

### Native macOS GUI
Starts the FastAPI/WebSocket backend on `127.0.0.1:8765` and opens a native macOS window:

```bash
uv run swarm_gui.py
```

Other UI modes:
- **Browser mode:** `uv run swarm_gui.py --browser` (opens `http://127.0.0.1:8765/?live=1` in your default browser).
- **Frontend dev mode:** Run `npm run dev` inside `swarm-widget-ui/`, then run `uv run swarm_gui.py --dev` to connect the native window to Vite (`http://localhost:5173/?live=1`).

---

## Running the Web MCP Server

Launch the standalone Streamable HTTP MCP server against any local workspace:

```bash
uv run python -m mcp_server --dir /path/to/workspace --port 8000
```

CLI options:
- `--dir PATH`: Target workspace directory to expose (default: current working directory).
- `--host HOST`: Host interface to bind to (default: `127.0.0.1`).
- `--port PORT`: Port to listen on (default: `8000`).
- `--read-only`: Disables mutating tools (`write_file`, `edit_file`, `delete_file`, `restore_backup`, `zsh`).
- `--session-id ID`: Custom subdirectory name inside `.backups/` (default: `mcp_YYYYMMDD_HHMMSS`).
- `--log-file PATH`: Unified tool-call log path (default: `logs/tool_calls_log.log`).

On startup, `mcp_server` loads or generates `MCP_CLIENT_ID` and `MCP_CLIENT_SECRET` in `.env`, persists OAuth tokens in `.oauth_tokens.json`, serves MCP at `http://<host>:<port>/mcp`, and prints a single concise `[MCP] ...` summary line per tool call. To expose it to a remote web AI client, tunnel port `8000` with `ngrok` or `cloudflared`.

---

## Additional Services & Pipelines

### 1. Resident Macro & HITL HUD Service (Auto-Start via `launchd`)

Running `macro_service` as a macOS LaunchAgent keeps PyObjC, Quartz, the Macro HUD, and `HitlModalHUD` warm in memory on `/tmp/agents-macro-synth.sock` so both macro triggers and agent/MCP `question` or `Security` approval modals pop up instantly without cold start.

1. Create `launchd/com.davidthele.agents.macro-synth.plist` (replace `/Users/YOUR_USER/path/to/local-agent-swarm` and `YOUR_GCP_PROJECT` with your actual paths):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.davidthele.agents.macro-synth</string>

    <key>ProgramArguments</key>
    <array>
        <string>/Users/YOUR_USER/path/to/local-agent-swarm/.venv/bin/python</string>
        <string>-m</string>
        <string>macro_synth.macro_service</string>
    </array>

    <key>WorkingDirectory</key>
    <string>/Users/YOUR_USER/path/to/local-agent-swarm</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>GOOGLE_CLOUD_PROJECT</key>
        <string>YOUR_GCP_PROJECT</string>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
    </dict>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>StandardOutPath</key>
    <string>/Users/YOUR_USER/.agents/logs/macro_service.out.log</string>

    <key>StandardErrorPath</key>
    <string>/Users/YOUR_USER/.agents/logs/macro_service.err.log</string>
</dict>
</plist>
```

2. Symlink the plist into `~/Library/LaunchAgents/` and load it:

```bash
ln -sf "$(pwd)/launchd/com.davidthele.agents.macro-synth.plist" ~/Library/LaunchAgents/
launchctl bootstrap "gui/$(id -u)" ~/Library/LaunchAgents/com.davidthele.agents.macro-synth.plist
```

3. Trigger a macro run (bind this command to a global hotkey via Karabiner-Elements, Raycast, or Shortcuts):

```bash
uv run -m macro_synth.macro_trigger
```

- **Abort at any time:** Press `Esc` or `Fn` during synthesis or execution.
- **Self-correction:** After execution finishes, type feedback into the HUD and press `Enter` to asynchronously launch `macro_synth.macro_analyzer` with the screen recording. Press `Esc` or click away to dismiss without running the analyzer.
- **Service-down notifications & fallback:** Triggering `macro_trigger` while `MacroService` is stopped displays a macOS notification. Agent/MCP `question` and `Security` prompts also display a notification and automatically fall back to a standalone queued subprocess (`python -m macro_synth.hud.hitl_modal`).
- **Restart / unload the service:**

```bash
launchctl kickstart -k "gui/$(id -u)/com.davidthele.agents.macro-synth"
# Or to stop and unload:
launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/com.davidthele.agents.macro-synth.plist
```

---

### 2. Activity Logger with `sleepwatcher`

The telemetry monitor (`pipelines/monitor/monitor_pipeline.py`) writes daily logs to `~/.agents/logs/moniter_data/YYYY-MM-DD/activity.log`. Because macOS sleep/wake cycles can stall `pynput` event taps, pairing it with `sleepwatcher` cleanly flushes and stops the monitor on sleep (`SIGTERM`) and restarts it on wake.

1. Install and start `sleepwatcher`:

```bash
brew install sleepwatcher
brew services start sleepwatcher
```

2. Create `~/.sleep` to gracefully stop the monitor when your Mac sleeps:

```bash
#!/bin/zsh
pkill -TERM -f "pipelines/monitor/monitor_pipeline.py"
```

3. Create `~/.wakeup` to restart the monitor when your Mac wakes (update `REPO_DIR` to your clone path):

```bash
#!/bin/zsh
REPO_DIR="/Users/YOUR_USER/path/to/local-agent-swarm"
LOG_OUT="$HOME/.agents/logs/monitor.log"

mkdir -p "$HOME/.agents/logs"

if ! pgrep -f "pipelines/monitor/monitor_pipeline.py" > /dev/null; then
    cd "$REPO_DIR"
    nohup "$REPO_DIR/.venv/bin/python" "$REPO_DIR/pipelines/monitor/monitor_pipeline.py" >> "$LOG_OUT" 2>&1 &
fi
```

4. Make both scripts executable and start immediately:

```bash
chmod +x ~/.sleep ~/.wakeup
~/.wakeup
```

---

### 3. Semantic Memory Ingestion

Ingest completed daily `activity.log` files into ChromaDB (skips today's active log, backs up the database to `~/.agents/db/backups/`, scrubs secrets, and reconciles chunks in 200-line batches):

```bash
uv run -m pipelines.log_ingestor_wrapper
```

With custom paths:

```bash
AGENTS_DB_DIR="$HOME/.agents/db" \
AGENTS_LOG_DIR="$HOME/.agents/logs/moniter_data" \
uv run -m pipelines.log_ingestor_wrapper
```

---

### 4. Manual Post-Mortem Analyzers

Run the multi-subagent swarm optimizer on any past session by chat ID or directory path:

```bash
uv run -m pipelines.swarm_analyzer <chat_id_or_path>
```

Run the macro video evaluator manually on a recorded run:

```bash
uv run -m macro_synth.macro_analyzer \
  ~/.agents/logs/macro_recordings/prompts/prompt_<timestamp>.txt \
  ~/.agents/logs/macro_recordings/outputs/output_<timestamp>.txt \
  ~/.agents/logs/macro_recordings/recordings/recording_<timestamp>.mp4 \
  --feedback ~/.agents/logs/macro_recordings/outputs/feedback_<timestamp>.txt
```

---

## Testing

Run the pytest suite (covers node cancellation, active thinking timeouts, graceful shutdown, session-organized backups, `.gitignore` filtering, `edit_file` shift projection, MCP permission filtering, and resident HUD modal queuing):

```bash
uv run pytest
```
