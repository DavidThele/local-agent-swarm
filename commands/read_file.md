# Command: ReadFile

**Description:**
Reads the contents of a file from the local file system. Can be used to read entire files or specific line ranges to save context window space.

**Attributes:**
- `path` (required): The absolute filepath, or path relative to the current chat workspace.
- `start_line` (optional): The line number to start reading from.
- `end_line` (optional): The line number to stop reading at.

**Example Usage (Full File):**
<ReadFile path="/Users/davidthele/Documents/project/src/main.ts" />

**Example Usage (Line Range):**
<ReadFile path="/Users/davidthele/Documents/project/src/main.ts" start_line="45" end_line="80" />