# Command: EditFile

**Description:**
Performs a surgical exact search-and-replace edit on an existing file. Optionally scope the match to 1-indexed `start_line`..`end_line` (inclusive) to disambiguate repeated snippets. Automatically projects stale line ranges forward after prior edits to the same file and saves a unified diff backup in `.backups/<session>/` (skipping `.gitignore`d files).

**Attributes:**
- `path` (required): Filepath (relative to workspace root or absolute).
- `start_line` (optional): 1-based start line (inclusive) to scope the search window.
- `end_line` (optional): 1-based end line (inclusive) to scope the search window.

**Child Tags:**
- `<OldStr>`: Exact text snippet to replace. Must match uniquely within the file (or scoped line window).
- `<NewStr>`: Replacement text (may be empty to delete the matched block).
- `<Summary>` (optional): Brief summary of the change for parent agents.

**Example Usage:**
<EditFile path="src/utils.py" start_line="10" end_line="25">
    <OldStr>def calculate_sum(a, b):
    return a + b</OldStr>
    <NewStr>def calculate_sum(a: float, b: float) -> float:
    return a + b</NewStr>
    <Summary>Added type annotations to calculate_sum.</Summary>
</EditFile>
