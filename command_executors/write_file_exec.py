import uuid
from pathlib import Path

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    target_path = attributes.get("path")
    if isinstance(content, dict):
        file_content = content.get("Content", "")
        summary = content.get("Summary", "No summary provided.")
    else:
        file_content = str(content)
        summary = "Wrote raw content."
        
    chat_dir = Path(context_state.get("local_chat_dir", ".agents/chats/default"))
    worker_id = context_state.get("worker_id", uuid.uuid4().hex[:8])
    
    if not target_path:
        return "[Error] WriteFile requires a 'path' attribute."
        
    try:
        target_file = Path(target_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(file_content)
            
        chat_dir.mkdir(parents=True, exist_ok=True)
        
        # Append mode ('a') so multiple writes by the same worker don't overwrite earlier logs
        full_log_path = chat_dir / f"{worker_id}_full.txt"
        with open(full_log_path, "a", encoding="utf-8") as f:
            f.write(f"=== Target Path: {target_path} ===\n{file_content}\n\n")
            
        summary_log_path = chat_dir / f"{worker_id}_summary.txt"
        with open(summary_log_path, "a", encoding="utf-8") as f:
            f.write(f"Modified File: {target_path}\nSummary: {summary}\n---\n")
            
        return f"[Success] File written to {target_path}. Summary: {summary}"
        
    except Exception as e:
        return f"[Error] Failed to write file {target_path}: {str(e)}"