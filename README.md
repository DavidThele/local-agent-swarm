# local-agent-swarm

Local autonomous agents with XML command execution, asynchronous delegation, and
semantic memory backed by ChromaDB.

## Install

Requires Python 3.11–3.13 (managed automatically via [`uv`](https://docs.astral.sh/uv/)):

```bash
uv sync
```

This creates a local `.venv`, installs the project in editable mode, and syncs
all runtime dependencies locked in `uv.lock` and `pyproject.toml` (including
`chromadb`, `google-genai`, `playwright`, and PyObjC frameworks).

Configure Google GenAI credentials using the environment-variable format
supported by the installed Google GenAI SDK (or a local `.env` file) before
starting a session.

## Start A Swarm Session

Run the CLI from the project directory:

```bash
uv run swarm_cli.py
```

The CLI prompts first for the task and then asks whether to run the performance
analyzer after the session completes.

The CLI uses the current working directory as the workspace root. File reads and
writes inside that directory proceed normally. Reads and writes outside it prompt
for approval; directory listings outside it are denied.

## Storage

- Global prompts, command schemas, configuration, and chat links live under
  `~/.agents`.
- The persistent semantic database and ingestion state use `~/.agents/db` by
  default. Existing database contents are preserved.
- Set `AGENTS_DB_DIR` to use another database and state directory.
- Set `AGENTS_LOG_DIR` to select the telemetry directory. Without it, logs are
  read from `./moniter_data` relative to the process working directory.

Example:

```bash
AGENTS_DB_DIR="$HOME/.agents/db" \
AGENTS_LOG_DIR="$HOME/path/to/moniter_data" \
uv run -m pipelines.log_ingestor_wrapper
```

The ingestion wrapper skips the current date and processes prior
`YYYY-MM-DD/activity.log` directories in chunks.

## Resident Macro Service

The macro synthesizer runs as a resident macOS LaunchAgent using the project's
`.venv/bin/python` interpreter so PyObjC, Quartz, the prompt router, and the
HUD are loaded once. The installed service listens on a per-user Unix socket.
Trigger a run with:

```bash
uv run -m macro_synth.macro_trigger
```

The compatibility command also triggers the resident service:

```bash
uv run macro_synth/macro_executor.py
```

The LaunchAgent definition is kept at
`launchd/com.davidthele.agents.macro-synth.plist`. The telemetry monitor is a
separate process and continues writing `moniter_data` independently.

## Configuration

Shell command whitelist and blacklist files are read from `~/.agents/config`
when present, with the repository `config/` files as fallback. Commands using
shell operators, pipelines, redirection, or chaining are rejected; approved
commands run without a shell.

The orchestrator roles and their XML command schemas are defined in `prompts/`
and `commands/`. Workers can read, write, list directories, and run approved
commands; orchestrators delegate work and manage child agents.