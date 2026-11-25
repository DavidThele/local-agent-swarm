# Command: FindFiles

**Description:**
Finds files across the workspace matching a glob pattern (e.g. `*.py`, `src/**/*.ts`). Automatically skips common build, dependency, and cache directories (`.git`, `.backups`, `node_modules`, `.venv`, `__pycache__`, etc.).

**Attributes:**
- `pattern` (required): Glob pattern matched against both relative paths and filenames.

**Example Usage:**
<FindFiles pattern="*.py" />
