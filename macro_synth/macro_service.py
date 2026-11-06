"""Resident macro service and Unix-socket trigger."""

import socket
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
import subprocess
from datetime import datetime
from macro_synth.context_capture import ScreenRecorder, build_prompt_context
from .runtime import LOGS_DIR

from AppKit import NSApplication, NSRunningApplication, NSWorkspace
from PyObjCTools import AppHelper

from infrastructure.debugging import debug_print
from infrastructure.parser import parse_llm_output
from infrastructure.prompt_router import send_prompt
from infrastructure.scrubber import scrub_text
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
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    recordings_dir = LOGS_DIR / "macro_recordings"
    video_path = recordings_dir / f"recording_{timestamp}.mp4"
    prompt_path = recordings_dir / f"prompt_{timestamp}.txt"
    xml_path = recordings_dir / f"output_{timestamp}.txt"
    
    recorder = ScreenRecorder()
    full_prompt = ""
    llm_xml = ""

    try:
        workspace = NSWorkspace.sharedWorkspace()
        target_app = workspace.frontmostApplication()
        current_pid = NSRunningApplication.currentApplication().processIdentifier()
        if target_app and target_app.processIdentifier() == current_pid:
            target_app = getattr(hud, "last_external_app", None)

        with ThreadPoolExecutor(max_workers=1) as context_pool:
            context_future = context_pool.submit(build_prompt_context, target_app=target_app)

            cancelled, user_message, extra_pages = hud.wait_for_user_prompt(target_app=target_app)
            if cancelled:
                debug_print("[MacroSynth] Run cancelled by user from prompt box.", "warning")
                return

            hud.update(status_text="Finalizing context capture...", wait=True)
            clipboard, recent_log, deep_dom, screenshots, labels = context_future.result()

        input_events.start_physical_kill_switch(hud)

        all_screenshots = list(screenshots)
        extra_labels = []
        for desc, png_bytes in extra_pages:
            all_screenshots.append((f"User Added Context ({desc})", png_bytes))
            extra_labels.append(desc)

        user_request_block = f"<UserExplicitRequest>\n{scrub_text(user_message)}\n</UserExplicitRequest>\n\n" if user_message else ""
        extra_context_block = f"<UserAddedContextPages>\nExtra contexts: {', '.join(extra_labels)}.\n</UserAddedContextPages>\n\n" if extra_labels else ""

        instructions = load_macro_instructions()
        full_prompt = (
            f"{instructions}\n\n"
            f"{user_request_block}"
            f"{extra_context_block}"
            f"<ClipboardContent>\n{clipboard}\n</ClipboardContent>\n\n"
            f"<RecentActivityLog>\n{recent_log}\n</RecentActivityLog>\n\n"
            f"<DeepActiveDOM>\n{deep_dom}\n</DeepActiveDOM>\n\n"
            f"<ApplicationScreenshots>\nDefault screenshots: {labels}.\n</ApplicationScreenshots>\n\n"
            "Synthesize the <MacroAnalysis> and the XML action sequence with per-step reasoning now."
        )

        hud.update(status_text="Parsing actions with Gemini...", wait=True)
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(
                send_prompt,
                prompt_text=full_prompt,
                model=MODEL_TO_USE,
                print_cost=True,
                image_data=all_screenshots,
            )
            while not future.done():
                if abort_event.is_set():
                    debug_print("[MacroSynth] Aborted during API request.", "error")
                    return
                time.sleep(0.05)
            llm_xml, _, _ = future.result()

        commands = parse_llm_output(llm_xml)
        if not commands:
            hud.update(status_text="No valid XML actions returned.", wait=True)
            return

        # Start recording right before action execution begins
        recorder.start(video_path)
        # Give screencapture 150ms to spin up its capture session
        time.sleep(0.15)
            
        if execute_macro_commands(commands, hud):
            hud.update(status_text="Macro sequence completed!", wait=True)
        else:
            hud.update(status_text="Macro sequence stopped before completion.", wait=True)

    except Exception as exc:
        debug_print(f"[MacroSynth] Worker failed: {exc}", "error")
        hud.update(status_text=f"Error: {exc}", wait=True)
    finally:
        input_events.stop_physical_kill_switch()
        recorder.stop()
        
        if not abort_event.is_set() and not getattr(hud, "prompt_cancelled", False):
            hud.hide_after_delay(2.5)

        # Launch the analyzer independently so it doesn't block the resident service
        if full_prompt and llm_xml:
            recordings_dir.mkdir(parents=True, exist_ok=True)
            prompt_path.write_text(full_prompt, encoding="utf-8")
            xml_path.write_text(llm_xml, encoding="utf-8")
            
            subprocess.Popen([
                sys.executable, "-m", "macro_synth.macro_analyzer", 
                str(prompt_path), str(xml_path), str(video_path)
            ])
            
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
    NSApplication.sharedApplication().run()


if __name__ == "__main__":
    main()