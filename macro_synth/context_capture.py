"""Capture the active macOS context used to synthesize a macro."""

import json
import re
import signal
import subprocess
import time
from collections import deque
from datetime import datetime
from pathlib import Path

import ApplicationServices
import io
import objc
from PIL import Image, ImageDraw, ImageFont
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
    SCREEN_CONTEXTS_DIR,
)

def _save_screenshot_to_log(png_bytes: bytes, label: str) -> None:
    """Saves the screenshot buffer to the screen_contexts log folder."""
    try:
        SCREEN_CONTEXTS_DIR.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:19]
        safe_label = re.sub(r"[^\w\-.]+", "_", label).strip("_") or "screen"
        file_path = SCREEN_CONTEXTS_DIR / f"{timestamp}_{safe_label}.png"
        file_path.write_bytes(png_bytes)
        debug_print(f"[MacroSynth] Saved screenshot artifact to {file_path}", "debug")
    except Exception as exc:
        debug_print(f"[MacroSynth] Failed saving screenshot to {SCREEN_CONTEXTS_DIR}: {exc}", "warning")

def _overlay_coordinate_grid(
    png_bytes: bytes,
    label: str = "screenshot",
    offset_x: int = 0,
    offset_y: int = 0,
    app_width: int | None = None,
    app_height: int | None = None,
    step: int = 50,
) -> bytes:
    """
    Pastes the application screenshot onto a full-screen point canvas at its actual screen
    coordinates, overlays a 50px grid, logs to disk, and returns the PNG bytes.
    Handles Retina scaling seamlessly.
    """
    main_rect = Quartz.CGDisplayBounds(Quartz.CGMainDisplayID())
    target_width = int(main_rect.size.width)
    target_height = int(main_rect.size.height)
    
    debug_print(f"[MacroSynth] Overlaying coordinate grid on screenshot for '{label}'...", "debug")
    with Image.open(io.BytesIO(png_bytes)) as base_img:
        img = base_img.convert("RGBA")
        
        # Fix Retina scaling: force the raw pixel image down to logical screen points
        if app_width and app_height:
            img = img.resize((app_width, app_height), Image.Resampling.BILINEAR)
        else:
            # For full-screen captures
            img = img.resize((target_width, target_height), Image.Resampling.BILINEAR)

        canvas = Image.new("RGBA", (target_width, target_height), (20, 22, 28, 255))
        canvas.paste(img, (offset_x, offset_y))

        overlay = Image.new("RGBA", (target_width, target_height), (255, 255, 255, 0))
        draw = ImageDraw.Draw(overlay)

        grid_color = (0, 200, 255, 60)
        major_color = (255, 50, 50, 110)
        text_color = (255, 255, 255, 200)
        bg_chip_color = (0, 0, 0, 160)
        font = ImageFont.load_default()

        # Vertical grid lines
        for x in range(0, target_width + 1, step):
            col = major_color if (x % 200 == 0) else grid_color
            draw.line([(x, 0), (x, target_height)], fill=col, width=1)

        # Horizontal grid lines
        for y in range(0, target_height + 1, step):
            col = major_color if (y % 200 == 0) else grid_color
            draw.line([(0, y), (target_width, y)], fill=col, width=1)

        # Coordinate tags
        for x in range(0, target_width + 1, step * 2):
            for y in range(0, target_height + 1, step * 2):
                coord_label = f"{x},{y}"
                bbox = draw.textbbox((x + 2, y + 2), coord_label, font=font)
                draw.rectangle([bbox[0] - 1, bbox[1] - 1, bbox[2] + 1, bbox[3] + 1], fill=bg_chip_color)
                draw.text((x + 2, y + 2), coord_label, fill=text_color, font=font)

        composited = Image.alpha_composite(canvas, overlay).convert("RGB")
        out_buf = io.BytesIO()
        composited.save(out_buf, format="PNG", optimize=True)
        final_bytes = out_buf.getvalue()

        debug_print(f"[MacroSynth] Finished overlaying grid on screenshot for '{label}'.", "debug")
        _save_screenshot_to_log(final_bytes, label)
        return final_bytes

def _unpack_ax_value(ax_val):
    try:
        val_str = str(ax_val)
        nums = re.findall(r"[-+]?\d*\.\d+|\d+", val_str)
        if len(nums) >= 2:
            return [round(float(nums[0]), 1), round(float(nums[1]), 1)]
    except Exception:
        pass
    return None

def get_deep_active_dom(target_app=None, max_depth: int = DEEP_DOM_MAX_DEPTH) -> dict:
    with objc.autorelease_pool():
        workspace = NSWorkspace.sharedWorkspace()
        app = target_app or workspace.frontmostApplication()
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
            
            # Extract absolute screen coordinates to offset the grid correctly
            bounds = window.get(Quartz.kCGWindowBounds, {})
            offset_x = int(bounds.get("X", 0))
            offset_y = int(bounds.get("Y", 0))
            app_w = int(bounds.get("Width", 0))
            app_h = int(bounds.get("Height", 0))

            # Strip the invisible drop shadow
            image = Quartz.CGWindowListCreateImage(
                Quartz.CGRectNull,
                Quartz.kCGWindowListOptionIncludingWindow,
                window[Quartz.kCGWindowNumber],
                Quartz.kCGWindowImageBoundsIgnoreFraming,
            )
            if image is None:
                continue
            bitmap = NSBitmapImageRep.alloc().initWithCGImage_(image)
            png_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
            if png_data:
                processed_bytes = _overlay_coordinate_grid(
                    bytes(png_data), 
                    label=app_name,
                    offset_x=offset_x,
                    offset_y=offset_y,
                    app_width=app_w,
                    app_height=app_h
                )
                screenshots.append((app_name, processed_bytes))

        debug_print(
            f"[MacroSynth] Captured {len(screenshots)}/{len(app_names)} requested application screenshot(s).",
            "debug",
        )
        return screenshots

def get_frontmost_window_description(target_app=None) -> str:
    with objc.autorelease_pool():
        workspace = NSWorkspace.sharedWorkspace()
        app = target_app or workspace.frontmostApplication()
        if not app:
            return "Screen Context"
        app_name = str(app.localizedName() or "App")
        pid = app.processIdentifier()
        app_ref = ApplicationServices.AXUIElementCreateApplication(pid)
        err, focused_win = ApplicationServices.AXUIElementCopyAttributeValue(app_ref, "AXFocusedWindow", None)
        if err == 0 and focused_win:
            err_t, title = ApplicationServices.AXUIElementCopyAttributeValue(focused_win, "AXTitle", None)
            if err_t == 0 and title:
                title_str = str(title).strip()
                if title_str:
                    if len(title_str) > 42:
                        title_str = title_str[:39] + "..."
                    return f"{app_name} - {title_str}"
        return app_name

def capture_screen_context_exclude_hud(
    hud_window_number: int | None = None,
    target_app=None,
) -> tuple[str, bytes] | None:
    with objc.autorelease_pool():
        desc = get_frontmost_window_description(target_app=target_app)
        if hud_window_number and hud_window_number > 0:
            list_option = (
                Quartz.kCGWindowListOptionOnScreenBelowWindow
                | Quartz.kCGWindowListExcludeDesktopElements
            )
            window_id = int(hud_window_number)
        else:
            list_option = Quartz.kCGWindowListOptionOnScreenOnly
            window_id = Quartz.kCGNullWindowID

        image = Quartz.CGWindowListCreateImage(
            Quartz.CGRectInfinite,
            list_option,
            window_id,
            Quartz.kCGWindowImageBoundsIgnoreFraming,
        )
        if image is None:
            return None
        bitmap = NSBitmapImageRep.alloc().initWithCGImage_(image)
        png_data = bitmap.representationUsingType_properties_(NSPNGFileType, None)
        if not png_data:
            return None
        
        processed_bytes = _overlay_coordinate_grid(bytes(png_data), label=desc)
        debug_print(f"[MacroSynth] Added full-screen page context with grid: '{desc}'", "info")
        return (desc, processed_bytes)
    
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

def build_prompt_context(
    target_app=None,
    recorder: "ScreenRecorder | None" = None,
    recording_output_path: Path | None = None,
) -> tuple[str, str, str, list[tuple[str, bytes]], str]:
    """
    Builds context artifacts. If a recorder is supplied, recording starts
    right before the final context payload is returned to be sent to Gemini.
    """
    raw_log_tail = get_last_n_log_lines()
    scrubbed_log = scrub_text(raw_log_tail)
    debug_print(
        f"[MacroSynth] Captured {len(raw_log_tail.splitlines())} telemetry line(s) and scrubbed them for the prompt.",
        "debug",
    )

    deep_dom = get_deep_active_dom(target_app=target_app)
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

    # Start the screen recording right before dispatching the prompt to Gemini
    if recorder and recording_output_path:
        recorder.start(recording_output_path)

    return scrubbed_clipboard, scrubbed_log, scrubbed_dom, screenshots, labels

class ScreenRecorder:
    def __init__(self):
        self.process = None
        self.filepath = None

    def start(self, filepath: Path | None = None):
        if filepath:
            self.filepath = Path(filepath)
        if not self.filepath:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self.filepath = SCREEN_CONTEXTS_DIR / f"run_{timestamp}.mp4"

        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        self.process = subprocess.Popen(
            ["screencapture", "-v", str(self.filepath)],
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        debug_print(f"[ScreenRecorder] Started recording to {self.filepath.name}", "system")

    def stop(self, post_buffer_seconds: float = 1.0):
        """Stops the recording after an optional trailing buffer delay."""
        if self.process:
            if post_buffer_seconds > 0:
                debug_print(f"[ScreenRecorder] Waiting {post_buffer_seconds}s buffer before stopping recording...", "system")
                time.sleep(post_buffer_seconds)

            self.process.send_signal(signal.SIGINT)
            self.process.wait()
            self.process = None
            debug_print(f"[ScreenRecorder] Stopped recording.", "system")