"""Synthetic keyboard, mouse, scroll, and kill-switch events."""

import time

import Quartz
from AppKit import NSEvent

from infrastructure.debugging import debug_print
from .runtime import (
    KEY_COMBO_DOWN_TIME_MS,
    KEY_COMBO_UP_TIME_MS,
    KEY_PRESS_DOWN_TIME_MS,
    KEY_PRESS_UP_TIME_MS,
    MOUSE_CLICK_DOWN_TIME_MS,
    MOUSE_CLICK_MOVE_DELAY_MS,
    MOUSE_CLICK_UP_TIME_MS,
    MOUSE_SCROLL_DELAY_MS,
    MOUSE_SCROLL_MOVE_DELAY_MS,
    SYNTHETIC_EVENT_TAG,
    TYPING_BUFFER_TIME_MS,
    abort_event,
    abort_lock,
    global_event_monitor,
    kill_switch_stop_event,
)
import macro_synth.runtime as runtime

KEYCODE_MAP = {
    "a": 0x00, "s": 0x01, "d": 0x02, "f": 0x03, "h": 0x04, "g": 0x05, "z": 0x06, "x": 0x07,
    "c": 0x08, "v": 0x09, "b": 0x0B, "q": 0x0C, "w": 0x0D, "e": 0x0E, "r": 0x0F, "y": 0x10,
    "t": 0x11, "1": 0x12, "2": 0x13, "3": 0x14, "4": 0x15, "6": 0x16, "5": 0x17, "=": 0x18,
    "9": 0x19, "7": 0x1A, "-": 0x1B, "8": 0x1C, "0": 0x1D, "]": 0x1E, "o": 0x1F, "u": 0x20,
    "[": 0x21, "i": 0x22, "p": 0x23, "enter": 0x24, "return": 0x24, "l": 0x25, "j": 0x26,
    "'": 0x27, "k": 0x28, ";": 0x29, "\\": 0x2A, ",": 0x2B, "/": 0x2C, "n": 0x2D, "m": 0x2E,
    ".": 0x2F, "tab": 0x30, "space": 0x31, "`": 0x32, "backspace": 0x33, "delete": 0x75,
    "esc": 0x35, "escape": 0x35, "cmd": 0x37, "command": 0x37, "shift": 0x38, "capslock": 0x39,
    "alt": 0x3A, "option": 0x3A, "ctrl": 0x3B, "control": 0x3B, "cmd_r": 0x36,
    "left": 0x7B, "right": 0x7C, "down": 0x7D, "up": 0x7E,
    "f1": 0x7A, "f2": 0x78, "f3": 0x63, "f4": 0x76, "f5": 0x60, "f6": 0x61,
}

MODIFIER_FLAGS = {
    "cmd": Quartz.kCGEventFlagMaskCommand,
    "command": Quartz.kCGEventFlagMaskCommand,
    "shift": Quartz.kCGEventFlagMaskShift,
    "alt": Quartz.kCGEventFlagMaskAlternate,
    "option": Quartz.kCGEventFlagMaskAlternate,
    "ctrl": Quartz.kCGEventFlagMaskControl,
    "control": Quartz.kCGEventFlagMaskControl,
}


def start_physical_kill_switch(hud):
    global_monitor = None
    kill_switch_stop_event.clear()

    def is_abort_event(event, event_type):
        if event_type == Quartz.kCGEventKeyDown:
            keycode = Quartz.CGEventGetIntegerValueField(
                event, Quartz.kCGKeyboardEventKeycode
            )
            return keycode == KEYCODE_MAP["esc"]

        flags = Quartz.CGEventGetFlags(event)
        function_flag = getattr(Quartz, "kCGEventFlagMaskSecondaryFn", 0)
        return bool(function_flag and flags & function_flag)

    def trigger_abort():
        with abort_lock:
            if abort_event.is_set():
                return
            debug_print("\n[KillSwitch] Abort triggered by user key press!", "error")
            abort_event.set()
        if getattr(hud, "resident", False):
            hud.hide_instantly()
        else:
            hud.dismiss_instantly()

    try:
        global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
            Quartz.NSKeyDownMask | Quartz.NSFlagsChangedMask,
            lambda event: trigger_abort()
            if event.keyCode() == KEYCODE_MAP["esc"]
            or bool(
                getattr(Quartz, "kCGEventFlagMaskSecondaryFn", 0)
                and event.modifierFlags()
                & getattr(Quartz, "kCGEventFlagMaskSecondaryFn", 0)
            )
            else None,
        )
        runtime.global_event_monitor = global_monitor
    except Exception as exc:
        debug_print(f"[KillSwitch] Global monitor setup warning: {exc}", "warning")

    def tap_callback(proxy, event_type, event, refcon):
        if event_type in (Quartz.kCGEventKeyDown, Quartz.kCGEventFlagsChanged) and is_abort_event(event, event_type):
            user_data = Quartz.CGEventGetIntegerValueField(event, Quartz.kCGEventSourceUserData)
            if user_data != SYNTHETIC_EVENT_TAG:
                trigger_abort()
        return event

    def run_tap_loop():
        mask = Quartz.CGEventMaskBit(Quartz.kCGEventKeyDown) | Quartz.CGEventMaskBit(Quartz.kCGEventFlagsChanged)
        tap = Quartz.CGEventTapCreate(
            Quartz.kCGSessionEventTap,
            Quartz.kCGHeadInsertEventTap,
            Quartz.kCGEventTapOptionListenOnly,
            mask,
            tap_callback,
            None,
        )
        if not tap:
            debug_print("[KillSwitch] Quartz CGEventTap skipped (Accessibility permissions missing). Relying on AppKit monitor.", "warning")
            return
        source = Quartz.CFMachPortCreateRunLoopSource(None, tap, 0)
        loop = Quartz.CFRunLoopGetCurrent()
        Quartz.CFRunLoopAddSource(loop, source, Quartz.kCFRunLoopCommonModes)
        Quartz.CGEventTapEnable(tap, True)
        while not abort_event.is_set() and not kill_switch_stop_event.is_set():
            Quartz.CFRunLoopRunInMode(Quartz.kCFRunLoopDefaultMode, 0.05, True)

    import threading
    threading.Thread(target=run_tap_loop, daemon=True).start()


def stop_physical_kill_switch():
    kill_switch_stop_event.set()
    monitor = runtime.global_event_monitor
    if monitor is not None:
        try:
            NSEvent.removeMonitor_(monitor)
        except Exception as exc:
            debug_print(f"[KillSwitch] Monitor cleanup warning: {exc}", "warning")
    runtime.global_event_monitor = None


def _post_synthetic_event(event, allow_after_abort=False):
    with abort_lock:
        if abort_event.is_set() and not allow_after_abort:
            return False
        Quartz.CGEventPost(Quartz.kCGHIDEventTap, event)
        return True


def press_single_key(key_name: str, count: int = 1):
    cleaned = key_name.strip().lower() if isinstance(key_name, str) else str(key_name)
    keycode = KEYCODE_MAP.get(cleaned)
    if keycode is None:
        debug_print(f"[MacroSynth] Skipping invalid key: '{key_name}'", "warning")
        return
    for _ in range(count):
        if abort_event.is_set():
            return
        if not _post_tagged_key_event(keycode, True):
            debug_print(f"[MacroSynth] Failed to post key-down event for '{key_name}'", "warning")
            return
        time.sleep(KEY_PRESS_DOWN_TIME_MS / 1000.0)
        _post_tagged_key_event(keycode, False)
        time.sleep(KEY_PRESS_UP_TIME_MS / 1000.0)


def _post_tagged_key_event(keycode, key_down, flags=0):
    event = Quartz.CGEventCreateKeyboardEvent(None, keycode, key_down)
    if flags:
        Quartz.CGEventSetFlags(event, flags)
    Quartz.CGEventSetIntegerValueField(event, Quartz.kCGEventSourceUserData, SYNTHETIC_EVENT_TAG)
    return _post_synthetic_event(event, allow_after_abort=not key_down)


def press_key_combo(combo_str: str):
    if not isinstance(combo_str, str):
        debug_print(f"[MacroSynth] Invalid combo string format: {combo_str}", "warning")
        return
    flags = 0
    main_key = None
    for part in (piece.strip().lower() for piece in combo_str.split("+") if piece.strip()):
        if part in MODIFIER_FLAGS:
            flags |= MODIFIER_FLAGS[part]
        elif part in KEYCODE_MAP:
            main_key = part
        else:
            debug_print(f"[MacroSynth] Unrecognized token in key combo '{combo_str}': '{part}'", "warning")

    if main_key is None:
        debug_print(f"[MacroSynth] Skipping key combo '{combo_str}': No valid trigger key found.", "warning")
        return
    if abort_event.is_set():
        return
    if not _post_tagged_key_event(KEYCODE_MAP[main_key], True, flags):
        debug_print(f"[MacroSynth] Failed to post key combo '{combo_str}'", "warning")
        return
    time.sleep(KEY_COMBO_DOWN_TIME_MS / 1000.0)
    _post_tagged_key_event(KEYCODE_MAP[main_key], False, flags)
    time.sleep(KEY_COMBO_UP_TIME_MS / 1000.0)


def type_unicode_string(text: str):
    if not isinstance(text, str):
        debug_print(f"[MacroSynth] Non-string passed to type_unicode_string: {text}", "warning")
        text = str(text)
    for char in text:
        if abort_event.is_set():
            return
        if char in ("\n", "\t"):
            press_single_key("enter" if char == "\n" else "tab")
            continue
        for key_down in (True, False):
            event = Quartz.CGEventCreateKeyboardEvent(None, 0, key_down)
            Quartz.CGEventKeyboardSetUnicodeString(event, len(char), char)
            Quartz.CGEventSetIntegerValueField(event, Quartz.kCGEventSourceUserData, SYNTHETIC_EVENT_TAG)
            _post_synthetic_event(event, allow_after_abort=not key_down)
        time.sleep(TYPING_BUFFER_TIME_MS / 1000.0)


def click_mouse(x: float, y: float, button="left", count=1) -> bool:
    if abort_event.is_set():
        return False
    try:
        point = Quartz.CGPointMake(float(x), float(y))
    except (ValueError, TypeError) as exc:
        debug_print(f"[MacroSynth] Invalid mouse coordinates ({x}, {y}): {exc}", "warning")
        return False
    is_right = str(button).strip().lower() == "right"
    down_type = Quartz.kCGEventRightMouseDown if is_right else Quartz.kCGEventLeftMouseDown
    up_type = Quartz.kCGEventRightMouseUp if is_right else Quartz.kCGEventLeftMouseUp
    mouse_button = Quartz.kCGMouseButtonRight if is_right else Quartz.kCGMouseButtonLeft
    move_evt = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, point, mouse_button)
    Quartz.CGEventSetIntegerValueField(move_evt, Quartz.kCGEventSourceUserData, SYNTHETIC_EVENT_TAG)
    if not _post_synthetic_event(move_evt):
        debug_print(f"[MacroSynth] Failed to move mouse to ({x}, {y})", "warning")
        return False
    time.sleep(MOUSE_CLICK_MOVE_DELAY_MS / 1000.0)
    for click_num in range(1, count + 1):
        down_evt = Quartz.CGEventCreateMouseEvent(None, down_type, point, mouse_button)
        Quartz.CGEventSetIntegerValueField(down_evt, Quartz.kCGMouseEventClickState, click_num)
        Quartz.CGEventSetIntegerValueField(down_evt, Quartz.kCGEventSourceUserData, SYNTHETIC_EVENT_TAG)
        if not _post_synthetic_event(down_evt):
            debug_print(f"[MacroSynth] Failed to post mouse-down event at ({x}, {y})", "warning")
            return False
        time.sleep(MOUSE_CLICK_DOWN_TIME_MS / 1000.0)
        up_evt = Quartz.CGEventCreateMouseEvent(None, up_type, point, mouse_button)
        Quartz.CGEventSetIntegerValueField(up_evt, Quartz.kCGMouseEventClickState, click_num)
        Quartz.CGEventSetIntegerValueField(up_evt, Quartz.kCGEventSourceUserData, SYNTHETIC_EVENT_TAG)
        _post_synthetic_event(up_evt, allow_after_abort=True)
        time.sleep(MOUSE_CLICK_UP_TIME_MS / 1000.0)
    return True


def scroll_mouse(dx: int, dy: int, x=None, y=None):
    if abort_event.is_set():
        return
    try:
        dx_val = int(dx)
        dy_val = int(dy)
    except (ValueError, TypeError) as exc:
        debug_print(f"[MacroSynth] Invalid scroll delta values ({dx}, {dy}): {exc}", "warning")
        return
    if x is not None and y is not None:
        try:
            point = Quartz.CGPointMake(float(x), float(y))
            move_evt = Quartz.CGEventCreateMouseEvent(None, Quartz.kCGEventMouseMoved, point, Quartz.kCGMouseButtonLeft)
            Quartz.CGEventSetIntegerValueField(move_evt, Quartz.kCGEventSourceUserData, SYNTHETIC_EVENT_TAG)
            if not _post_synthetic_event(move_evt):
                debug_print(f"[MacroSynth] Failed to move mouse before scroll to ({x}, {y})", "warning")
                return
            time.sleep(MOUSE_SCROLL_MOVE_DELAY_MS / 1000.0)
        except (ValueError, TypeError) as exc:
            debug_print(f"[MacroSynth] Invalid coordinates for scroll ({x}, {y}): {exc}", "warning")
    scroll_evt = Quartz.CGEventCreateScrollWheelEvent(None, Quartz.kCGEventUnitLine, 2, dy_val, dx_val)
    Quartz.CGEventSetIntegerValueField(scroll_evt, Quartz.kCGEventSourceUserData, SYNTHETIC_EVENT_TAG)
    _post_synthetic_event(scroll_evt)
    time.sleep(MOUSE_SCROLL_DELAY_MS / 1000.0)


def interruptible_wait(ms: int):
    try:
        abort_event.wait(timeout=max(0.0, float(ms) / 1000.0))
    except (ValueError, TypeError) as exc:
        debug_print(f"[MacroSynth] Invalid wait duration ({ms}): {exc}", "warning")