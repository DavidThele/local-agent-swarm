"""Resident macro service and Unix-socket trigger."""

import socket
import threading
import time
from concurrent.futures import ThreadPoolExecutor

from PyObjCTools import AppHelper

from infrastructure.debugging import debug_print
from infrastructure.parser import parse_llm_output
from infrastructure.prompt_router import send_prompt
from .action_runner import execute_macro_commands
from .context_capture import build_prompt_context
from . import input_events
from .hud_overlay import MacroHUD
from .runtime import (
    GLOBAL_ROOT,
    MODEL_TO_USE,
    REPO_ROOT,
    SOCKET_PATH,
    abort_event,
)


def load_macro_instructions() -> str:
    global_path = GLOBAL_ROOT / "prompts" / "macro_instructions.md"
    if global_path.exists():
        return global_path.read_text(encoding="utf-8")
    return (REPO_ROOT / "prompts" / "macro_instructions.md").read_text(encoding="utf-8")


def run_macro_once(hud: MacroHUD):
    input_events.start_physical_kill_switch(hud)
    try:
        hud.update(status_text="Capturing DOM & recent telemetry...")
        clipboard, recent_log, deep_dom, screenshots, labels = build_prompt_context()
        instructions = load_macro_instructions()
        full_prompt = (
            f"{instructions}\n\n"
            f"<ClipboardContent>\n{clipboard}\n</ClipboardContent>\n\n"
            f"<RecentActivityLog>\n{recent_log}\n</RecentActivityLog>\n\n"
            f"<DeepActiveDOM>\n{deep_dom}\n</DeepActiveDOM>\n\n"
            f"<ApplicationScreenshots>\nScreenshots are attached for: {labels}.\n"
            "Each image is labeled with its application name.\n</ApplicationScreenshots>\n\n"
            "Synthesize the <MacroAnalysis> and the XML action sequence with per-step reasoning now."
        )
        hud.update(status_text="Parsing actions with Gemini...")
        debug_print("[MacroSynth] Submitting multimodal macro prompt.", "debug")
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                send_prompt,
                prompt_text=full_prompt,
                model=MODEL_TO_USE,
                print_cost=True,
                image_data=screenshots,
            )
            while not future.done():
                if abort_event.is_set():
                    debug_print("[MacroSynth] Aborted during API request.", "error")
                    return
                time.sleep(0.05)
            llm_xml, _, _ = future.result()

        commands = parse_llm_output(llm_xml)
        debug_print(f"[MacroSynth] Parsed {len(commands)} XML command block(s).", "debug")
        if not commands:
            hud.update(status_text="No valid XML actions returned.")
            return
        if execute_macro_commands(commands, hud):
            hud.update(status_text="Macro sequence completed!")
        else:
            hud.update(status_text="Macro sequence stopped before completion.")
    except Exception as exc:
        debug_print(f"[MacroSynth] Worker failed: {exc}", "error")
        hud.update(status_text=f"Error: {exc}")
    finally:
        input_events.stop_physical_kill_switch()
        if not abort_event.is_set():
            hud.hide_after_delay(2.5)


class MacroService:
    def __init__(self, hud: MacroHUD):
        self.hud = hud
        self.run_lock = threading.Lock()
        self.worker = None
        self.stop_event = threading.Event()
        self.server_thread = None

    def start(self):
        SOCKET_PATH.parent.mkdir(parents=True, exist_ok=True)
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass
        self.server_thread = threading.Thread(target=self._serve, daemon=True)
        self.server_thread.start()
        debug_print(f"[MacroSynth] Resident service listening on {SOCKET_PATH}.", "success")

    def _serve(self):
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(SOCKET_PATH))
            server.listen(4)
            server.settimeout(0.5)
            while not self.stop_event.is_set():
                try:
                    connection, _ = server.accept()
                except socket.timeout:
                    continue
                with connection:
                    request = connection.recv(64).decode("utf-8", errors="replace").strip()
                    if request != "trigger":
                        connection.sendall(b"error: unknown request\n")
                    elif self.worker and self.worker.is_alive():
                        connection.sendall(b"busy\n")
                    else:
                        abort_event.clear()
                        self.hud.show_for_run()
                        self.worker = threading.Thread(target=self._run, daemon=True)
                        self.worker.start()
                        connection.sendall(b"accepted\n")
        try:
            SOCKET_PATH.unlink()
        except FileNotFoundError:
            pass

    def _run(self):
        with self.run_lock:
            run_macro_once(self.hud)


def trigger_service() -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(SOCKET_PATH))
        client.sendall(b"trigger\n")
        return client.recv(64).decode("utf-8").strip()


def main():
    hud = MacroHUD(width=420, height=140, resident=True)
    hud.setup_window()
    service = MacroService(hud)
    service.start()
    AppHelper.runConsoleEventLoop()


if __name__ == "__main__":
    main()
