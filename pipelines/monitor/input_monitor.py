import threading
from pynput import keyboard, mouse

from infrastructure.debugging import debug_print

input_events = []
event_lock = threading.Lock()
current_scroll = None

def flush_scroll():
    global current_scroll
    if current_scroll is not None:
        input_events.append(
            f"Mouse scrolled at ({current_scroll['x']}, {current_scroll['y']}) "
            f"total_delta({current_scroll['dx']}, {current_scroll['dy']})"
        )
        current_scroll = None

def on_press(key):
    with event_lock:
        flush_scroll()
        input_events.append(f"{key} pressed")

def on_release(key):
    with event_lock:
        flush_scroll()
        input_events.append(f"{key} released")

def on_click(x, y, button, pressed):
    with event_lock:
        flush_scroll()
        action = "pressed" if pressed else "released"
        input_events.append(f"Mouse {button} {action} at ({round(x, 1)}, {round(y, 1)})")

def on_scroll(x, y, dx, dy):
    global current_scroll
    with event_lock:
        if current_scroll is None:
            current_scroll = {"x": round(x, 1), "y": round(y, 1), "dx": dx, "dy": dy}
        else:
            current_scroll["x"] = round(x, 1)
            current_scroll["y"] = round(y, 1)
            current_scroll["dx"] += dx
            current_scroll["dy"] += dy

def start_listeners():
    k_listener = keyboard.Listener(on_press=on_press, on_release=on_release)
    m_listener = mouse.Listener(on_click=on_click, on_scroll=on_scroll)
    k_listener.start()
    m_listener.start()
    return k_listener, m_listener

def stop_listeners(k_listener, m_listener):
    debug_print("Stopping input listeners...", "info")
    if k_listener and k_listener.is_alive():
        k_listener.stop()
    if m_listener and m_listener.is_alive():
        m_listener.stop()

    if k_listener:
        k_listener.join(timeout=1.0)
    if m_listener:
        m_listener.join(timeout=1.0)
    debug_print("Input listeners stopped.", "info")

def get_and_clear_events():
    """Safely retrieves the current buffer of events and clears the global queue."""
    with event_lock:
        flush_scroll()
        current = input_events.copy()
        input_events.clear()
        return current

def clear_events():
    """Drops all events (useful for blocklisted apps)."""
    with event_lock:
        global current_scroll
        current_scroll = None
        input_events.clear()