# Command: ListDirectory

**Description:**
Lists the contents of a directory as an indented tree. Prefer this over using `<Zsh>` with `ls` as it is computationally cheaper and automatically includes file size and total line count metadata so you can decide whether to read a whole file or a line range.

- Each text file displays its size and total line count: `[FILE] app.py (4.2 KB, 128 lines)`.
- Binary files are labeled `(size, binary)` without line counting.
- Files larger than **3 MB** skip line counting and display a warning recommending against reading them directly.
- Common build, dependency, and cache directories (`.git`, `node_modules`, `.venv`, `__pycache__`, `dist`, `build`, `.next`, etc.) are automatically ignored.

**Attributes:**
- `path` (required): The absolute filepath (or path relative to workspace root) of the directory to list.
- `depth` (optional): Specify the max depth to recursively list files through. Default is `1`. Must be a non-negative integer.

**Example Usage:**
<ListDirectory path="/Users/davidthele/Documents/project/src" depth="3" />
