# Command: WriteFile

**Description:**
Creates a new file (including parent directories if needed) or performs a full-file overwrite of an existing file. Every tracked mutation automatically saves a unified diff backup in `.backups/<session>/` (files matching `.gitignore` are skipped).
For targeted changes to an existing file, prefer `<EditFile>` instead of `<WriteFile>`.

**Attributes:**
- `path` (required): The absolute filepath (or path relative to workspace root) of the file to create or overwrite.

**Child Tags:**
- `<Content>`: Full file text to write.
- `<Summary>`: A brief summary of what was written. This is what parent agents will see.

**Example Usage:**
<WriteFile path="src/utils.py">
    <Content>
def calculate_sum(a: float, b: float) -> float:
    return a + b
    </Content>
    <Summary>Created utils.py with calculate_sum helper.</Summary>
</WriteFile>
