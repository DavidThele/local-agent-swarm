# local-agent-swarm

A local-first, macOS-native autonomous agent swarm and OS-level macro synthesizer. It combines a hierarchical multi-agent execution engine, a persistent semantic memory store (ChromaDB), a resident Programming-by-Demonstration macro service, and a self-improving post-mortem optimizer.

---

## Defining Features

Compared to general-purpose cloud or framework-heavy agent swarms, `local-agent-swarm` is built around direct macOS integration, strict local safety, and continuous self-optimization:

- **Hierarchical Async Delegation (XML Protocol):** A 3-tier architecture (`Main Orchestrator` -> `Sub-Orchestrator` -> `Worker`) where orchestrators spawn background daemon threads via `<SpawnAgent>` and synchronize with `<WaitForAgents mode="any|all" />`. Custom XML parsing with automatic CDATA wrapping prevents raw code and shell operators from breaking tool calls.
- **Self-Improving Memory & Skill Synthesis:** After a session finishes, `swarm_analyzer` audits every agent's JSON execution trace (`*_trace.json`) and worker summaries, automatically upgrading `~/.agents/AGENTS.md` with durable environment facts and saving reusable multi-step procedures to `~/.agents/skills/`.
- **Resident OS-Level Macro Synthesizer (Programming by Demonstration):** A background macOS service (`macro_service`) that reads your recent telemetry, clipboard, Accessibility (AX) DOM tree, and grid-overlaid window screenshots to finish repetitive workflows using Quartz keyboard/mouse events. Includes a floating WebKit HUD, on-device Apple Speech Recognition, an `Esc`/`Fn` physical kill switch, and a video-based `macro_analyzer` that watches screen recordings of its own runs to refine `macro_instructions.md`.
- **Privacy-First Local Telemetry & Semantic Memory:** A background activity monitor logs app switches, compact AX UI trees, and inputs while automatically suspending inside `Passwords`, `System Settings`, `Keychain Access`, or any `AXSecureTextField`. A rolling `SecretRedactor` and regex scrubber strip API keys, JWTs, SSNs, and credit cards before anything is written to disk or sent to an LLM.
- **Zero-Shell Security Sandbox & Workspace Scoping:** `<Zsh>` commands run with `shell=False` and reject pipes, redirects, and subshells. Whitelisted read-only utilities execute silently; everything else pauses for Human-in-the-Loop (HITL) approval. File reads/writes outside the active workspace root also require explicit approval (with diff preview).
- **Native macOS Command Center UI:** An optional PyObjC/WKWebView desktop app (`swarm_gui.py`) powered by FastAPI, WebSockets, and React Flow. Visualizes the live agent DAG, streams command logs, handles HITL approvals inline, and features an animated sprite mascot ("Byte").
- **Tiered Model Routing & Live Cost Tracking:** Routes high-level planning to stronger models (`gemini-3.8-flash`) and high-frequency worker/ingestion loops to lightweight models (`gemini-3.1-flash-lite` / `gemini-3.5-flash-lite`), logging per-turn token and USD costs directly to traces.

---

## Installation

### 1. Prerequisites
- **macOS** (required for PyObjC, Quartz, Accessibility APIs, WebKit HUD, and native speech recognition)
- **Python 3.11 - 3.13** managed via [`uv`](https://docs.astral.sh/uv/)
- **Node.js 18+** (only required if building or developing the `swarm-widget-ui` frontend)
- **Google Cloud / Vertex AI** project with Gemini API access

### 2. Install Python Dependencies
```bash
git clone <your-repo-url> local-agent-swarm
cd local-agent-swarm
uv sync
```

This creates `.venv`, installs the project in editable mode, and syncs all locked dependencies (`chromadb`, `google-genai`, `playwright`, `fastapi`, `uvicorn`, `pynput`, and PyObjC frameworks).

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

### Credentials & Environment Variables
The prompt router (`infrastructure/prompt_router.py`) connects to Gemini via Vertex AI (`vertexai=True`, `location="global"`). Authenticate with Application Default Credentials:

```bash
gcloud auth application-default login
```

Create a `.env` file in the repository root (or export these in your shell):

```bash
# Required for Vertex AI routing
GOOGLE_CLOUD_PROJECT="your-gcp-project-id"

# Optional path overrides (defaults shown)
AGENTS_DB_DIR="$HOME/.agents/db"
AGENTS_LOG_ROOT="$HOME/.agents/logs"
AGENTS_LOG_DIR="$HOME/.agents/logs/moniter_data"
MACRO_SERVICE_SOCKET="${TMPDIR:-/tmp}/agents-macro-synth.sock"
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

### Security Lists
Edit `config/cmd_whitelist.md` (or `~/.agents/config/cmd_whitelist.md`) to control which read-only commands execute without prompting. Shell operators (`|`, `>`, `<`, `&`, `;`, `` ` ``, `$(`, `${`) are always blocked by `cmd_blacklist.md` and a hardcoded baseline filter.

### Macro & Monitor Tuning
- **Macro timing & model:** `macro_synth/runtime.py` (`MODEL_TO_USE`, `LOG_LINES_TO_SEND`, `MAX_APP_SCREENSHOTS`, key/mouse delay constants).
- **HUD scale & position:** `macro_synth/hud/hud_config.py` (`HUD_SCALE`, `HUD_POS_X`, `HUD_POS_Y`, margins).
- **Monitor blocklist & polling:** `pipelines/monitor/config.py` (`BLOCKLIST`, `INTERVAL_SECONDS`, `MAX_UI_TREE_DEPTH`).

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

## Additional Services & Pipelines

### 1. Resident Macro Service (Auto-Start via `launchd`)

Running `macro_service` as a macOS LaunchAgent keeps PyObjC, Quartz, the prompt router, and the WebKit HUD warm in memory so triggers respond instantly over a Unix socket.

1. Create `launchd/com.davidthele.agents.macro-synth.plist` (replace `/Users/YOUR_USER/path/to/local-agent-swarm` and `YOUR_GCP_PROJECT` with your actual paths):

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "[http://www.apple.com/DTDs/PropertyList-1.0.dtd](http://www.apple.com/DTDs/PropertyList-1.0.dtd)">
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

4. Make both scripts executable:

```bash
chmod +x ~/.sleep ~/.wakeup
```

To start the monitor immediately without waiting for a wake event:

```bash
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

Run the swarm optimizer on any past session by chat ID or directory path:

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