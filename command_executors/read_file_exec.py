import os

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    path = attributes.get("path")
    start_line = attributes.get("start_line")
    end_line = attributes.get("end_line")
    
    if not path or not os.path.exists(path):
        return f"[Error] File not found at path: {path}"
        
    try:
        with open(path, "r", encoding="utf-8") as f:
            lines = f.readlines()
            
        if start_line and end_line:
            start = max(0, int(start_line) - 1)
            end = min(len(lines), int(end_line))
            snippet = "".join(lines[start:end])
            return f"--- File Snippet ({path}, lines {start_line}-{end_line}) ---\n{snippet}"
        else:
            return f"--- File Contents ({path}) ---\n" + "".join(lines)
            
    except Exception as e:
        return f"[Error] Could not read file {path}: {str(e)}"