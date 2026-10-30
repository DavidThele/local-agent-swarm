import os
from pathlib import Path

def get_tree(dir_path: Path, current_depth: int, max_depth: int) -> list:
    if current_depth > max_depth:
        return []
        
    results = []
    try:
        for item in dir_path.iterdir():
            if item.is_dir():
                results.append(f"{'  ' * current_depth}[DIR] {item.name}/")
                results.extend(get_tree(item, current_depth + 1, max_depth))
            else:
                results.append(f"{'  ' * current_depth}[FILE] {item.name}")
    except PermissionError:
        results.append(f"{'  ' * current_depth}[Permission Denied]")
        
    return results

def execute(attributes: dict, content: dict, context_state: dict) -> str:
    path = attributes.get("path")
    try:
        depth = int(attributes.get("depth", 1))
    except (TypeError, ValueError):
        return "[Error] ListDirectory depth must be an integer."
    if depth < 0:
        return "[Error] ListDirectory depth must be non-negative."
    
    if not path or not os.path.exists(path):
        return f"[Error] Directory not found: {path}"
        
    target_dir = Path(path)
    if not target_dir.is_dir():
        return f"[Error] Path is not a directory: {path}"
        
    tree = get_tree(target_dir, 0, depth)
    return "\n".join(tree)