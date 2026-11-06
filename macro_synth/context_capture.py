"""Capture the active macOS context used to synthesize a macro."""

import json
import re
from collections import deque
from datetime import datetime

import ApplicationServices
import objc
import Quartz
from AppKit import (
    NSBitmapImageRep,
    NSPasteboard,
    NSPNGFileType,
    NSStringPboardType,
    NSWorkspace,
)

from infrastructure.debugging import debug_print
from infrastructure.scrubber import scrub_text
from .runtime import (
    DATA_DIR,
    DEEP_DOM_MAX_DEPTH,
    DEEP_DOM_MAX_VALUE_LEN,
    MAX_APP_SCREENSHOTS,
    LOG_LINES_TO_SEND,
)


def _unpack_ax_value(ax_val):
    try:
        val_str = str(ax_val)
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", val_str)
        if len(nums) >= 2:
            return [round(float(nums[0]), 1), round(float(nums[1]), 1)]
    except Exception:
        pass
    return None


def get_deep_active_dom(max_depth: int = DEEP_DOM_MAX_DEPTH) -> dict:
    with objc.autorelease_pool():
        workspace = NSWorkspace.sharedWorkspace()
        app = workspace.frontmostApplication()
        if not app:
            return {"app": "Unknown", "tree": {}}

        app_name = app.localizedName()
        pid = app.processIdentifier()
        app_ref = ApplicationServices.AXUIElementCreateApplication(pid)

        def traverse(element, depth):
            if depth > max_depth:
                return "..."

            err, role = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXRole", None)
            if role in ("AXMenuBar", "AXMenu", "AXMenuItem"):
                return None

            node = {}
            if err == 0 and role:
                node["role"] = str(role)

            for attr_name, key_name in (
                ("AXTitle", "title"),
                ("AXDescription", "desc"),
                ("AXPlaceholderValue", "placeholder"),
                ("AXRoleDescription", "role_desc"),
            ):
                err, val = ApplicationServices.AXUIElementCopyAttributeValue(element, attr_name, None)
                if err == 0 and val:
                    val_s = str(val).strip()
                    if val_s:
                        node[key_name] = val_s[:300]

            err, val = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXValue", None)
            if err == 0 and val is not None:
                val_s = str(val)
                if val_s:
                    node["value"] = val_s[:DEEP_DOM_MAX_VALUE_LEN]
                    if len(val_s) > DEEP_DOM_MAX_VALUE_LEN:
                        node["value"] += "...[truncated]"

            for attr_name, key_name in (("AXPosition", "pos"), ("AXSize", "size")):
                err, val = ApplicationServices.AXUIElementCopyAttributeValue(element, attr_name, None)
                coords = _unpack_ax_value(val) if err == 0 and val is not None else None
                if coords:
                    node[key_name] = coords

            err, children = ApplicationServices.AXUIElementCopyAttributeValue(element, "AXChildren", None)
            if err == 0 and children:
                child_list = []
                for child in children:
                    child_node = traverse(child, depth + 1)
                    if child_node:
                        child_list.append(child_node)
                if child_list:
                    node["children"] = child_list
            return node

        err, focused_win = ApplicationServices.AXUIElementCopyAttributeValue(app_ref, "AXFocusedWindow", None)
        tree = traverse(focused_win, 0) if err == 0 and focused_win else traverse(app_ref, 0)
        return {"active_app": app_name, "pid": pid, "window_tree": tree}


def get_clipboard_text() -> str:
    with objc.autorelease_pool():
        content = NSPasteboard.generalPasteboard().stringForType_(NSStringPboardType)
        return str(content) if content else ""


def get_recent_app_names(log_text: str) -> list[str]:
    app_names = []
    for match in re.finditer(r"Active App Changed:\s*(.+?)\s*$", log_text, re.MULTILINE):
        app_name = match.group(1).strip()
        if app_name and app_name not in app_names:
            app_names.append(app_name)
    selected_apps = app_names[-MAX_APP_SCREENSHOTS:]
    debug_print(f"[MacroSynth] Selected {len(selected_apps)} recent application(s) for screenshot capture.", "debug")
    return selected_apps


def get_visible_app_screenshots(app_names: list[str]) -> list[tuple[str, bytes]]:
    with objc.autorelease_pool():
        windows = Quartz.CGWindowListCopyWindowInfo(
            Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements,
            Quartz.kCGNullWindowID,
        ) or []
        screenshots = []
        for app_name in app_names:
            candidates = [
                window for window in windows
                if window.get(Quartz.kCGWindowOwnerName, "") == app_name
                and window.get(Quartz.kCGWindowLayer, 0) == 0
                and window.get(Quartz.kCGWindowBounds, {}).get("Width", 0) > 1
                and window.get(Quartz.kCGWindowBounds, {}).get("Height", 0) > 1
            ]
            if not candidates:
                continue
            window = max(
                candidates,
                key=lambda item: item[Quartz.kCGWindowBounds]["Width"] * item[Quartz.kCGWindowBounds]["Height"],
            )
            image = Quartz.CGWindowListCreateImage(
                Quartz.CGRectNull,
                Quartz.kCGWindowListOptionIncludingWindow,
                window[Quartz.kCGWindowNumber],
                Quartz.kCGWindowImageDefault,
            )
            if image is None:
                continue
            bitmap = NSBitmapImageRep.alloc().initWithCGImage_(image)
            png_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
            if png_data:
                screenshots.append((app_name, bytes(png_data)))

        debug_print(
            f"[MacroSynth] Captured {len(screenshots)}/{len(app_names)} requested application screenshot(s).",
            "debug",
        )
        return screenshots


def get_last_n_log_lines(n: int = LOG_LINES_TO_SEND) -> str:
    today_str = datetime.now().strftime("%Y-%m-%d")
    log_file = DATA_DIR / today_str / "activity.log"
    if not log_file.exists() and DATA_DIR.exists():
        folders = sorted(folder for folder in DATA_DIR.iterdir() if folder.is_dir())
        if folders:
            log_file = folders[-1] / "activity.log"
    if not log_file.exists():
        return "[No activity.log found]"
    with log_file.open("r", encoding="utf-8", errors="ignore") as log_file_handle:
        return "".join(deque(log_file_handle, maxlen=n))


def build_prompt_context() -> tuple[str, str, str, list[tuple[str, bytes]], str]:
    raw_log_tail = get_last_n_log_lines()
    scrubbed_log = scrub_text(raw_log_tail)
    debug_print(
        f"[MacroSynth] Captured {len(raw_log_tail.splitlines())} telemetry line(s) and scrubbed them for the prompt.",
        "debug",
    )

    deep_dom = get_deep_active_dom()
    scrubbed_dom = scrub_text(json.dumps(deep_dom, indent=2))
    scrubbed_clipboard = scrub_text(get_clipboard_text())
    recent_apps = get_recent_app_names(raw_log_tail)
    if not recent_apps and deep_dom.get("active_app"):
        recent_apps = [deep_dom["active_app"]]
    screenshots = get_visible_app_screenshots(recent_apps)
    labels = ", ".join(name for name, _ in screenshots) or "none"
    debug_print(
        f"[MacroSynth] Prepared DOM, clipboard, and {len(screenshots)} screenshot attachment(s): {labels}.",
        "debug",
    )
    return scrubbed_clipboard, scrubbed_log, scrubbed_dom, screenshots, labels
