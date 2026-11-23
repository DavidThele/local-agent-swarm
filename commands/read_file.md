# Command: ReadFile

**Description:**
Reads the contents of a file from the local file system. Every output line is prefixed with its 1-based line number (`12 | <line>`), and the header reports the total line count of the file. Use `start_line` and/or `end_line` to read targeted slices of large files and save context window space.

**Attributes:**
- `path` (required): The absolute filepath, or path relative to the current chat workspace.
- `start_line` (optional): 1-based line number to start reading from (inclusive). If provided without `end_line`, reads from `start_line` through the end of the file.
- `end_line` (optional): 1-based line number to stop reading at (inclusive). If provided without `start_line`, reads from line `1` through `end_line`.

**Example Usage (Full File):**
<ReadFile path="/Users/davidthele/Documents/project/src/main.ts" />

**Example Usage (Line Range):**
<ReadFile path="/Users/davidthele/Documents/project/src/main.ts" start_line="45" end_line="80" />

**Example Usage (From Line to End of File):**
<ReadFile path="/Users/davidthele/Documents/project/src/main.ts" start_line="120" />
