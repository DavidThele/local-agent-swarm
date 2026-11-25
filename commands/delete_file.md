# Command: DeleteFile

**Description:**
Deletes a single file from the workspace after saving its full-content unified diff backup to `.backups/<session>/` (skipping `.gitignore`d files). Deleted files can be restored with `<RestoreBackup>`.

**Attributes:**
- `path` (required): Filepath (relative to workspace root or absolute) of the file to delete.

**Example Usage:**
<DeleteFile path="src/deprecated_helper.py" />
