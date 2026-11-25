# Command: SearchCode

**Description:**
Searches text files in the workspace for a plain-text substring or regular expression. Returns `path:line_number: line_text` entries, capped to protect context size. Skips binary files and ignored directories.

**Attributes:**
- `query` (required): Substring or regex pattern to search for.
- `glob` (optional): Glob filter to restrict searched files (e.g. `*.py`, `src/**/*.ts`).
- `is_regex` (optional): `"true"` or `"false"` (default `"false"`).

**Example Usage:**
<SearchCode query="def run_agent" glob="*.py" />
