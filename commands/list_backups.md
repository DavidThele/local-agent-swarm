# Command: ListBackups

**Description:**
Lists recent unified `.diff` backup files stored under `.backups/<session>/`, sorted newest-first. Returns paths relative to `.backups/` (e.g. `<session>/<timestamp>_edit_<file>.diff`) that can be passed directly to `<RestoreBackup>`.

**Attributes:**
- `limit` (optional): Maximum number of backups to return (default `20`).
- `session_id` (optional): Filter backups to a specific session subdirectory inside `.backups/`.

**Example Usage:**
<ListBackups limit="20" />
