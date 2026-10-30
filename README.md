# local-agent-swarm

Local autonomous agents with XML command execution, asynchronous delegation, and
semantic memory backed by ChromaDB.

## Install

Use Python 3.10 or newer:

```bash
python3 -m pip install -e .
```

The project installs its runtime dependencies from `pyproject.toml`, including
`chromadb` and `google-genai`.

Configure Google GenAI credentials using the environment-variable format
supported by the installed Google GenAI SDK before starting a session.

## Start A Swarm Session

Run the CLI from the project directory:

```bash
python3 swarm_cli.py "Describe the task for the agent swarm"
```

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
python3 -m pipelines.log_ingestor_wrapper
```

The ingestion wrapper skips the current date and processes prior
`YYYY-MM-DD/activity.log` directories in chunks.

## Configuration

Shell command whitelist and blacklist files are read from `~/.agents/config`
when present, with the repository `config/` files as fallback. Commands using
shell operators, pipelines, redirection, or chaining are rejected; approved
commands run without a shell.

The orchestrator roles and their XML command schemas are defined in `prompts/`
and `commands/`. Workers can read, write, list directories, and run approved
commands; orchestrators delegate work and manage child agents.
