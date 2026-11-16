import re
import objc
from AppKit import NSWorkspace
import ApplicationServices
from pipelines.monitor.config import MAX_UI_TREE_DEPTH, MAX_DOM_LENGTH, SKIP_VALUE_ROLES

def _unpack_ax_value(ax_val):
    try:
        val_str = str(ax_val)
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", val_str)
        if len(nums) >= 2:
            return [round(float(nums[0]), 1), round(float(nums[1]), 1)]
    except Exception:
        pass
    return None

def get_active_context(max_depth=MAX_UI_TREE_DEPTH):
    with objc.autorelease_pool():
        workspace = NSWorkspace.sharedWorkspace()
        app = workspace.frontmostApplication()

        if not app:
            return "Unknown", 0, {}, False

        app_name = app.localizedName()
        pid = app.processIdentifier()
        app_ref = ApplicationServices.AXUIElementCreateApplication(pid)

        # --- Check for secure input field focus ---
        is_secure_input = False
        err, focused_element = ApplicationServices.AXUIElementCopyAttributeValue(app_ref, "AXFocusedUIElement", None)
        if err == 0 and focused_element:
            err_sub, subrole = ApplicationServices.AXUIElementCopyAttributeValue(focused_element, "AXSubrole", None)
            if err_sub == 0 and str(subrole) == "AXSecureTextField":
                is_secure_input = True
        # ------------------------------------------

        def traverse(element, depth):
            if depth > max_depth:
                return "..."

            err, role = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXRole", None)
            if role in ["AXMenuBar", "AXMenu", "AXMenuItem"]:
                return None

            node_info = {}
            if err == 0 and role:
                node_info["role"] = role

            err, title = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXTitle", None)
            if err == 0 and title:
                node_info["title"] = title

            if role not in SKIP_VALUE_ROLES:
                err, val = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXValue", None)
                if err == 0 and val and isinstance(val, str):
                    if len(val) > MAX_DOM_LENGTH:
                        node_info["value"] = val[:MAX_DOM_LENGTH] + "..."
                    else:
                        node_info["value"] = val

            err, pos_val = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXPosition", None)
            coords = _unpack_ax_value(pos_val) if err == 0 and pos_val is not None else None
            if coords:
                node_info["pos"] = coords

            err, children = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXChildren", None)
            if err == 0 and children:
                child_nodes = []
                for child in children:
                    c_node = traverse(child, depth + 1)
                    if c_node:
                        child_nodes.append(c_node)
                if child_nodes:
                    node_info["children"] = child_nodes

            return node_info

        err, focused_window = ApplicationServices.AXUIElementCopyAttributeValue(app_ref, "AXFocusedWindow", None)

        if err == 0 and focused_window:
            window_tree = traverse(focused_window, 0)
            ui_tree = {
                "role": "AXApplication",
                "title": app_name,
                "children": [window_tree] if window_tree else [],
            }
        else:
            ui_tree = traverse(app_ref, 0)

        # Return the new flag as the fourth value
        return app_name, pid, ui_tree, is_secure_input

def compact_dom(node: dict | str | None, context_path: str = "") -> str:
    if not isinstance(node, dict):
        return ""

    elements = []
    role = node.get("role", "").replace("AX", "")
    title = node.get("title") or node.get("desc") or node.get("placeholder")
    value = node.get("value")
    pos = node.get("pos")

    current_path = context_path
    if role in ("Window", "Sheet", "Dialog", "Application") and title:
        current_path = f"{context_path} > {title}" if context_path else title

    interactive_roles = {
        "Button", "TextField", "TextArea", "Link", "CheckBox",
        "RadioButton", "PopUpButton", "ComboBox", "MenuItem", "StaticText"
    }

    if pos and (title or value or role in interactive_roles):
        parts = [f"[{role}]"] if role else []
        if title:
            clean_title = " ".join(str(title).split())[:60]
            parts.append(f'"{clean_title}"')
        if value:
            clean_val = " ".join(str(value).split())[:60]
            parts.append(f'(Val: "{clean_val}")')

        node_str = " ".join(parts)
        prefix = f"{current_path} > " if current_path else ""
        elements.append(f"{prefix}{node_str}")

    for child in node.get("children", []):
        child_str = compact_dom(child, current_path)
        if child_str:
            elements.append(child_str)

    return " | ".join(elements)