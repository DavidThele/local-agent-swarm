import uuid
from pathlib import Path

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    target_path = attributes.get("path")
    file_content = content.get("Content", "")
    summary = content.get("Summary", "No summary provided.")
    
    chat_dir = Path(context_state.get("local_chat_dir", ".agents/chats/default"))
    worker_id = context_state.get("worker_id", uuid.uuid4().hex[:8])
    
    if not target_path:
        return "[Error] WriteFile requires a 'path' attribute."
        
    try:
        # 1. Write the actual target file
        target_file = Path(target_path)
        target_file.parent.mkdir(parents=True, exist_ok=True)
        with open(target_file, "w", encoding="utf-8") as f:
            f.write(file_content)
            
        # 2. Write the full output to the isolated chat directory for logging
        full_log_path = chat_dir / f"{worker_id}_full.txt"
        with open(full_log_path, "w", encoding="utf-8") as f:
            f.write(f"Target Path: {target_path}\n\n{file_content}")
            
        # 3. Write the summary output to the isolated chat directory
        summary_log_path = chat_dir / f"{worker_id}_summary.txt"
        with open(summary_log_path, "w", encoding="utf-8") as f:
            f.write(f"Modified File: {target_path}\nSummary: {summary}")
            
        # 4. Return just the summary to the LLM context to save tokens
        return f"[Success] File written to {target_path}. Summary: {summary}"
        
    except Exception as e:
        return f"[Error] Failed to write file {target_path}: {str(e)}"