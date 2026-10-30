import os
from pathlib import Path
from infrastructure.workspace import is_within_workspace, request_file_access, resolve_workspace_path

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    path = attributes.get("path")
    start_line = attributes.get("start_line")
    end_line = attributes.get("end_line")
    
    if not path:
        return "[Error] File path is required."

    workspace_root, target_path = resolve_workspace_path(
        path, context_state.get("workspace_root")
    )
    if not is_within_workspace(target_path, workspace_root):
        if not request_file_access("read", target_path):
            return f"[FILE_ACCESS_DENIED] Read denied for {target_path}."

    if not target_path.exists():
        return f"[Error] File not found at path: {path}"
        
    try:
        with open(target_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if start_line and end_line:
            start = max(0, int(start_line) - 1)
            end = min(len(lines), int(end_line))
            snippet = "".join(lines[start:end])
            return f"--- File Snippet ({target_path}, lines {start_line}-{end_line}) ---\n{snippet}"
        else:
            return f"--- File Contents ({target_path}) ---\n" + "".join(lines)
            
    except Exception as e:
        return f"[Error] Could not read file {path}: {str(e)}"