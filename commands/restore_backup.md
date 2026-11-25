# Command: RestoreBackup

**Description:**
Reverses a unified `.diff` backup file in `.backups/<session>/` to restore the target file to its pre-operation state (deletes newly created files, recreates deleted files, or reverse-patches edited/overwritten files).

**Attributes:**
- `backup_filename` (required): Backup path relative to `.backups/` (e.g. `session_id/20261125_120000_edit_src__app.py.diff`), as returned by `<ListBackups>`.

**Example Usage:**
<RestoreBackup backup_filename="my_session/20261125_120000_edit_src__app.py.diff" />
