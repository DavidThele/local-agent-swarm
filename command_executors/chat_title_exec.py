from infrastructure import ui_bridge
from infrastructure.workspace import rename_chat_instance


def execute(attributes: dict, content: dict | str, context_state: dict) -> str:
    if isinstance(content, dict):
        raw_title = content.get("Text", "")
        if isinstance(raw_title, list):
            raw_title = raw_title[0]
    else:
        raw_title = str(content) if content else ""

    raw_title = raw_title.strip()
    if not raw_title:
        return "[Error] <ChatTitle> cannot be empty."

    current_dir = context_state.get("local_chat_dir")
    if not current_dir:
        return "[Error] No active chat directory found in context state."

    new_slug, new_dir = rename_chat_instance(current_dir, raw_title)
    context_state["local_chat_dir"] = str(new_dir)
    context_state["chat_id"] = new_slug
    context_state["request_chat_title"] = False

    ui_bridge.emit("SESSION_UPDATED", {"chat_id": new_slug, "title": raw_title})

    return f"[Success] Chat directory renamed to '{new_slug}'."