import re
import uuid
from pathlib import Path
from infrastructure.logging import log

def resolve_workspace_path(path: str, workspace_root: str | Path | None = None) -> tuple[Path, Path]:
    root = Path(workspace_root or Path.cwd()).expanduser().resolve()
    requested = Path(path).expanduser()
    resolved = (requested if requested.is_absolute() else root / requested).resolve()
    return root, resolved

def is_within_workspace(path: Path, workspace_root: Path) -> bool:
    try:
        path.relative_to(workspace_root)
        return True
    except ValueError:
        return False

def request_file_access(
    operation: str,
    path: Path,
    diff_provider=None,
) -> bool:
    from infrastructure.concurrency import TERMINAL_LOCK

    with TERMINAL_LOCK:
        print(
            f"\n[File Access] {operation.upper()} request outside the authorized workspace:\n"
            f"File: {path}\n"
            "Approve? [y]es, [n]o, [d]iff: "
        )
        while True:
            response = input().strip().lower()
            if response in {"y", "n"}:
                return response == "y"
            if response == "d":
                if diff_provider is None:
                    print("[File Access] No diff is available for a read request.")
                else:
                    print(diff_provider())
                print("Approve? [y]es or [n]o: ")
                while True:
                    response = input().strip().lower()
                    if response in {"y", "n"}:
                        return response == "y"
                    print("Please enter 'y' or 'n'.")
            else:
                print("Please enter 'y', 'n', or 'd'.")

def init_global_workspace() -> Path:
    """
    Initializes the global workspace in the user's home directory (~/.agents).
    Creates necessary directories and the global AGENTS.md template.
    """
    global_root = Path.home() / ".agents"
    
    # Define the global directory structure
    dirs_to_create = [
        global_root,
        global_root / "tools",
        global_root / "skills",
        global_root / "chats",
        global_root / "prompts",
        global_root / "config",
        global_root / "db"
    ]
    
    # Create directories safely
    for d in dirs_to_create:
        d.mkdir(parents=True, exist_ok=True)
        
    # Initialize global AGENTS.md if it doesn't exist
    agents_md_path = global_root / "AGENTS.md"
    if not agents_md_path.exists():
        with open(agents_md_path, "w", encoding="utf-8") as f:
            f.write("# Global Agents Profile & Context\n\n")
            f.write("This file contains the foundational system context, user profile, ")
            f.write("and global rules for all agents in the swarm.\n\n")
            f.write("> **Note:** The Optimizer agent will append and modify this file dynamically.\n")
            
    return global_root

def create_chat_instance(chat_id: str = '') -> tuple[str, Path]:
    """
    Creates a new isolated subdirectory for a chat instance in the CURRENT working directory.
    Then, creates a symlink to this local chat directory in the global ~/.agents/chats/ folder.
    
    Returns:
        tuple containing the (chat_id, Path_object of the local chat directory)
    """
    global_root = init_global_workspace()
    global_chats_dir = global_root / "chats"
    
    # Generate a short, collision-resistant ID for clean folder names
    if chat_id == '':
        chat_id = uuid.uuid4().hex[:12]
        
    # Local chat directory in the current working directory
    local_root = Path.cwd() / ".agents"
    local_chat_dir = local_root / "chats" / chat_id
    local_chat_dir.mkdir(parents=True, exist_ok=True)
    
    # Define the symlink path in the global directory
    global_symlink_path = global_chats_dir / chat_id
    
    # Edge Case: Avoid symlinking if the command is run from the home directory 
    # to prevent a directory trying to symlink to itself
    if local_chat_dir.resolve() != global_symlink_path.resolve():
        
        # Clean up if a broken symlink or folder with the same ID already exists globally
        if global_symlink_path.is_symlink() or global_symlink_path.exists():
            if global_symlink_path.is_symlink():
                global_symlink_path.unlink()
            else:
                raise FileExistsError(
                    f"Chat ID already exists as a directory: {global_symlink_path}"
                )
                
        # Create the symlink pointing the global chat ID to the absolute path of the local chat directory
        global_symlink_path.symlink_to(local_chat_dir.resolve(), target_is_directory=True)
        log(f"[System] Symlink created: {global_symlink_path} -> {local_chat_dir.resolve()}", "system")
    else:
        log("[System] Running from home directory. No symlink needed.", "system")
    
    log(f"[System] Local chat instance created: {local_chat_dir.resolve()}", "success")
    return chat_id, local_chat_dir

def sanitize_chat_title(raw_title: str) -> str:
    """Converts a brief chat title into a clean, filesystem-safe directory slug."""
    cleaned = re.sub(r"[^\w\s-]", "", raw_title.strip().lower())
    slug = re.sub(r"[-\s]+", "_", cleaned).strip("_")
    return slug[:60] or uuid.uuid4().hex[:12]

def rename_chat_instance(current_chat_dir: str | Path, new_title: str) -> tuple[str, Path]:
    """
    Renames an existing local chat directory to a sanitized title slug and updates
    its corresponding symlink in ~/.agents/chats/.
    """
    global_root = init_global_workspace()
    global_chats_dir = global_root / "chats"

    old_dir = Path(current_chat_dir).resolve()
    old_id = old_dir.name
    chats_parent = old_dir.parent

    base_slug = sanitize_chat_title(new_title)
    new_slug = base_slug
    counter = 2

    # Ensure uniqueness locally and globally
    while (
        (chats_parent / new_slug).exists()
        and (chats_parent / new_slug).resolve() != old_dir
    ) or (
        (global_chats_dir / new_slug).exists()
        and not (global_chats_dir / new_slug).is_symlink()
    ):
        new_slug = f"{base_slug}_{counter}"
        counter += 1

    new_dir = chats_parent / new_slug

    if old_dir.exists() and old_dir != new_dir:
        old_dir.rename(new_dir)

    # Remove old global symlink if it points to the old directory
    old_symlink = global_chats_dir / old_id
    if old_symlink.is_symlink():
        old_symlink.unlink()

    # Create updated global symlink
    new_symlink = global_chats_dir / new_slug
    if new_dir.resolve() != new_symlink.resolve():
        if new_symlink.is_symlink():
            new_symlink.unlink()
        new_symlink.symlink_to(new_dir.resolve(), target_is_directory=True)

    log(f"[System] Renamed chat session '{old_id}' -> '{new_slug}'", "success")
    return new_slug, new_dir

if __name__ == "__main__":
    # Test the initialization
    new_chat_id, new_chat_dir = create_chat_instance()