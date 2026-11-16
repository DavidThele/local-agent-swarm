import os
import signal
import threading
from datetime import datetime
from Foundation import NSRunLoop, NSDate

from pipelines.monitor.config import BLOCKLIST, DATA_DIR, INTERVAL_SECONDS
from input_monitor import start_listeners, stop_listeners, get_and_clear_events, clear_events
from ui_context import get_active_context, compact_dom
from redactor import SecretRedactor

shutdown_event = threading.Event()

def sig_handler(signum, frame):
    if not shutdown_event.is_set():
        print(f"\n[!] Signal {signum} received. Initiating graceful shutdown...")
        shutdown_event.set()

signal.signal(signal.SIGINT, sig_handler)
signal.signal(signal.SIGTERM, sig_handler)

def main():
    if not os.path.exists(DATA_DIR):
        os.makedirs(DATA_DIR, exist_ok=True)

    today_str = datetime.now().strftime("%Y-%m-%d")
    daily_dir = os.path.join(DATA_DIR, today_str)
    os.makedirs(daily_dir, exist_ok=True)

    log_file_path = os.path.join(daily_dir, "activity.log")

    k_listener, m_listener = start_listeners()
    print(f"Starting monitor. Appending data to {log_file_path}")

    last_app_name = None
    last_ui_tree_str = None
    redactor = SecretRedactor(buffer_chars=60)
    
    # Track blocking state so we don't spam the console
    is_currently_blocked = False

    try:
        while not shutdown_event.is_set():
            try:
                NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(0.05))

                if shutdown_event.is_set():
                    break

                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                
                # Unpack the new is_secure_input flag
                app_name, pid, ax_tree, is_secure_input = get_active_context()

                # Trigger block logic if app is blocked OR if a password field is focused
                if app_name in BLOCKLIST or is_secure_input:
                    if not is_currently_blocked:
                        reason = "Secure input field focused" if is_secure_input else f"'{app_name}' is active and blocked"
                        print(f"[{timestamp}] {reason}. Suspending logging.")
                        is_currently_blocked = True
                        
                    clear_events()
                    NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(INTERVAL_SECONDS))
                    continue
                else:
                    if is_currently_blocked:
                        print(f"[{timestamp}] Safe context restored. Cycle resumed.")
                        is_currently_blocked = False

                current_events = get_and_clear_events()
                app_changed_line = None
                
                if app_name != last_app_name:
                    app_changed_line = f"[{timestamp}] Active App Changed: {app_name}"
                    last_app_name = app_name

                current_ui_str = compact_dom(ax_tree)
                ui_tree_line = None
                if current_ui_str and current_ui_str != last_ui_tree_str:
                    ui_tree_line = f"[{timestamp}] UI Tree Updated: {current_ui_str}"
                    last_ui_tree_str = current_ui_str

                if app_changed_line or ui_tree_line or current_events:
                    flush_lines = redactor.process_cycle(
                        timestamp=timestamp,
                        app_changed_line=app_changed_line,
                        ui_tree_line=ui_tree_line,
                        current_events=current_events
                    )

                    if flush_lines:
                        with open(log_file_path, "a", encoding="utf-8") as log_file:
                            for line in flush_lines:
                                log_file.write(line + "\n")
                        print(f"[{timestamp}] Appended {len(flush_lines)} new updates to log.")
                else:
                    print(f"[{timestamp}] No activity detected. Skipped.")

            except (KeyboardInterrupt, SystemExit):
                shutdown_event.set()
                break
            except Exception as e:
                print(f"Error during cycle: {e}")

            if not shutdown_event.is_set():
                NSRunLoop.currentRunLoop().runUntilDate_(NSDate.dateWithTimeIntervalSinceNow_(INTERVAL_SECONDS))

    finally:
        flush_lines = redactor.flush_all()
        if flush_lines:
            with open(log_file_path, "a", encoding="utf-8") as log_file:
                for line in flush_lines:
                    log_file.write(line + "\n")
                    
        stop_listeners(k_listener, m_listener)
        print("Shutdown complete. All resources safely released.")

if __name__ == "__main__":
    main()