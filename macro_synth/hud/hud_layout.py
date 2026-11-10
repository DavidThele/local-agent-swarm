import json
from pathlib import Path
import threading
import time
from AppKit import (
    NSApplication,
    NSApplicationActivateAllWindows,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSMakeRect,
    NSRunningApplication,
    NSScreen,
    NSWorkspace,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSNotificationCenter,
    NSWindowDidResignKeyNotification
)
import Quartz
import WebKit
from PyObjCTools import AppHelper
from infrastructure.debugging import debug_print
from ..context_capture import capture_screen_context_exclude_hud
from ..speech_engine import NativeSpeechEngine
from .hud_config import (
    BASE_CANVAS_HEIGHT,
    BASE_CANVAS_WIDTH,
    HUD_MARGIN_RIGHT,
    HUD_MARGIN_TOP,
    HUD_POS_X,
    HUD_POS_Y,
    HUD_SCALE,
    get_window_title_for_pid,
)
from .hud_bridge import (
    HUDDispatcher,
    HUDScriptMessageHandler,
    InteractiveHUDPanel,
)

def _load_hud_html(scale: float) -> str:
    """Reads and assembles hud.html, hud.css, and hud.js from the hud_assets directory."""
    assets_dir = Path(__file__).resolve().parent / "hud_assets"
    html_template = (assets_dir / "hud.html").read_text(encoding="utf-8")
    css_content = (assets_dir / "hud.css").read_text(encoding="utf-8")
    js_content = (assets_dir / "hud.js").read_text(encoding="utf-8")

    return (
        html_template.replace("__HUD_SCALE__", str(scale))
        .replace("__HUD_CSS__", css_content)
        .replace("__HUD_JS__", js_content)
    )


class MacroHUD:
    def __init__(
        self,
        width: int = BASE_CANVAS_WIDTH,
        height: int = BASE_CANVAS_HEIGHT,
        resident: bool = False,
        scale: float = HUD_SCALE,
        pos_x: float | None = HUD_POS_X,
        pos_y: float | None = HUD_POS_Y,
    ):
        self.scale = float(scale)
        self.width = int(round(width * self.scale))
        self.height = int(round(height * self.scale))
        self.pos_x = pos_x
        self.pos_y = pos_y
        self.resident = resident

        self.panel = None
        self.webview = None
        self.script_handler = None
        self.feedback_monitor = None
        self.feedback_global_monitor = None
        self.prompt_key_monitor = None
        self._refocus_timer = None

        # Native Speech Recognition Engine
        self.speech_engine = None

        self.dispatcher = HUDDispatcher.alloc().initWithHUD_(self)

        self.mode = "hidden" if resident else "loading"
        self.status_text = "Processing..."
        self.actions = []
        self.analysis = None

        # Synchronization for Interactive Prompt Phase
        self.prompt_event = threading.Event()
        self.prompt_cancelled = False
        self.user_request_text = ""
        self.added_context_pages: list[tuple[str, bytes]] = []
        self.last_external_app = None
        self.candidate_context_label = ""

        # Synchronization for Post-Execution Feedback
        self.feedback_event = threading.Event()
        self.feedback_text = ""
        self.feedback_cancelled = False

    def setup_window(self):
        """Must be called on the main thread before starting the worker thread."""
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        ws_nc = NSWorkspace.sharedWorkspace().notificationCenter()
        ws_nc.addObserverForName_object_queue_usingBlock_(
            "NSWorkspaceDidActivateApplicationNotification",
            None,
            None,
            self._on_app_activated,
        )

        x, y = self._compute_window_origin()

        style_mask = NSWindowStyleMaskBorderless
        self.panel = InteractiveHUDPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, self.width, self.height),
            style_mask,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.hud_ref = self

        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setFloatingPanel_(True)
        self.panel.setBecomesKeyOnlyIfNeeded_(False)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setOpaque_(False)
        self.panel.setAlphaValue_(0.0 if self.resident else 1.0)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        )
        # Register notification for window unfocus / resign key
        nc = NSApplication.sharedApplication().notificationCenter() if hasattr(NSApplication.sharedApplication(), "notificationCenter") else None
        # Register notification for window unfocus / resign key
        NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            NSWindowDidResignKeyNotification,
            self.panel,
            None,
            lambda note: AppHelper.callAfter(self._on_panel_resigned_key),
        )

        config = WebKit.WKWebViewConfiguration.alloc().init()
        user_controller = WebKit.WKUserContentController.alloc().init()
        self.script_handler = HUDScriptMessageHandler.alloc().initWithHUD_(self)
        user_controller.addScriptMessageHandler_name_(self.script_handler, "hudBridge")
        config.setUserContentController_(user_controller)

        self.webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, self.width, self.height),
            config,
        )
        self.webview.setValue_forKey_(False, "drawsBackground")

        html = _load_hud_html(self.scale)
        self.webview.loadHTMLString_baseURL_(html, None)

        self.panel.setContentView_(self.webview)
        self.panel.orderFrontRegardless()

        # Initialize speech engine hooks
        self.speech_engine = NativeSpeechEngine(
            on_partial_text=self._on_speech_partial,
            on_audio_levels=self._on_audio_levels,
        )
    def _on_speech_partial(self, text: str):
        def _push():
            if self.mode == "prompt" and self.webview:
                js = f"if (window.appendTranscript) {{ window.appendTranscript({json.dumps(text)}); }}"
                self.webview.evaluateJavaScript_completionHandler_(js, None)
        AppHelper.callAfter(_push)

    def _on_audio_levels(self, bands: list[float]):
        def _push():
            if self.mode == "prompt" and self.webview:
                js = f"if (window.setAudioLevels) {{ window.setAudioLevels({json.dumps(bands)}); }}"
                self.webview.evaluateJavaScript_completionHandler_(js, None)
        AppHelper.callAfter(_push)

    def _compute_window_origin(self) -> tuple[float, float]:
        screen_frame = NSScreen.mainScreen().visibleFrame()
        x = (
            float(self.pos_x)
            if self.pos_x is not None
            else screen_frame.origin.x + screen_frame.size.width - self.width - HUD_MARGIN_RIGHT
        )
        y = (
            float(self.pos_y)
            if self.pos_y is not None
            else screen_frame.origin.y + screen_frame.size.height - self.height - HUD_MARGIN_TOP
        )
        return x, y
    
    def set_scale(self, new_scale: float):
        """Dynamically updates the universal scalar and resizes the HUD window accordingly."""
        self.scale = float(new_scale)
        self.width = int(round(BASE_CANVAS_WIDTH * self.scale))
        self.height = int(round(BASE_CANVAS_HEIGHT * self.scale))
        if self.panel:
            x, y = self._compute_window_origin()
            self.panel.setFrame_display_(NSMakeRect(x, y, self.width, self.height), True)
        if self.webview:
            self.webview.setFrame_(NSMakeRect(0, 0, self.width, self.height))
            self._push_js_state()

    def _format_app_candidate_label(self, app) -> str:
        if not app:
            return "Current Screen"
        app_name = str(app.localizedName() or "Application")
        win_title = get_window_title_for_pid(app.processIdentifier())
        if win_title and win_title.lower() != app_name.lower():
            return f"{app_name} - {win_title}"
        return app_name

    def _schedule_prompt_refocus(self, delay: float = 0.15):
        """
        Allows external apps a brief pause to process activation and mouse clicks,
        then gracefully re-asserts keyboard focus into the prompt box.
        """
        if self._refocus_timer:
            try:
                self._refocus_timer.cancel()
            except Exception:
                pass

        def _do_refocus():
            if self.mode == "prompt" and self.panel and self.webview:
                def _main_refocus():
                    if self.mode == "prompt" and self.panel:
                        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                        self.panel.makeKeyAndOrderFront_(None)
                        self.panel.makeFirstResponder_(self.webview)
                        self.webview.evaluateJavaScript_completionHandler_(
                            "if (document.getElementById('hud-input')) document.getElementById('hud-input').focus();",
                            None,
                        )
                AppHelper.callAfter(_main_refocus)

        self._refocus_timer = threading.Timer(delay, _do_refocus)
        self._refocus_timer.daemon = True
        self._refocus_timer.start()

    def _on_panel_resigned_key(self):
        """Called whenever the panel loses key status."""
        if self.mode == "feedback":
            AppHelper.callAfter(self._handle_feedback_dismiss)
        elif self.mode == "prompt":
            self._schedule_prompt_refocus(0.15)

    def _on_app_activated(self, notification):
        try:
            app = notification.userInfo().objectForKey_("NSWorkspaceApplicationKey")
            current_pid = NSRunningApplication.currentApplication().processIdentifier()
            if app and app.processIdentifier() != current_pid:
                self.last_external_app = app
                self.candidate_context_label = self._format_app_candidate_label(app)
                if self.mode == "prompt":
                    self._push_js_state()
                    self._schedule_prompt_refocus(0.15)
                elif self.mode == "feedback":
                    self._handle_feedback_dismiss()
        except Exception:
            pass

    def _push_js_state(self, clear_input: bool = False, focus_input: bool = False):
        if not self.webview:
            return
        state_dict = {
            "scale": self.scale,
            "mode": self.mode,
            "statusText": self.status_text,
            "actions": self.actions,
            "addedContext": [desc for (desc, _) in self.added_context_pages],
            "candidateLabel": self.candidate_context_label,
            "clearInput": clear_input,
            "focusInput": focus_input,
        }
        js_code = f"if (window.updateHUD) {{ window.updateHUD({json.dumps(state_dict)}); }}"
        self.webview.evaluateJavaScript_completionHandler_(js_code, None)

    def _handle_js_message(self, data: dict):
        msg_type = data.get("type")
        if msg_type == "stop_listening":
            self._stop_speech_listening()
        elif msg_type == "submit_prompt":
            self._stop_speech_listening()
            self._stop_prompt_key_monitor()
            self.user_request_text = str(data.get("text") or "").strip()
            self._handle_send_clicked()
        elif msg_type == "cancel_prompt":
            self._stop_speech_listening()
            self._stop_prompt_key_monitor()
            self._handle_cancel_clicked()
        elif msg_type == "add_context":
            self._handle_add_context_clicked()
        elif msg_type == "remove_context":
            idx = data.get("index")
            if isinstance(idx, int) and 0 <= idx < len(self.added_context_pages):
                removed = self.added_context_pages.pop(idx)
                debug_print(f"[HUD] Removed context page: {removed[0]}", "data")
                if self.panel:
                    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                    self.panel.makeKeyAndOrderFront_(None)
                    self.panel.makeFirstResponder_(self.webview)
                self._push_js_state(focus_input=True)
        elif msg_type == "submit_feedback":
            self.feedback_cancelled = False
            # Allow empty string if user simply hits Enter on an empty input
            raw_text = data.get("text")
            self.feedback_text = str(raw_text).strip() if raw_text is not None else ""
            self._complete_feedback_submission()
        elif msg_type == "dismiss_feedback":
            self._handle_feedback_dismiss()
            
    def wait_for_user_prompt(self, target_app=None) -> tuple[bool, str, list[tuple[str, bytes]]]:
        self.prompt_event.clear()
        self.prompt_cancelled = False
        self.user_request_text = ""
        self.added_context_pages = []
        if target_app:
            self.last_external_app = target_app

        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_("beginPrompt:", None, True)
        self.prompt_event.wait()

        if not self.prompt_cancelled:
            time.sleep(0.12)

        return self.prompt_cancelled, self.user_request_text, list(self.added_context_pages)

    def wait_for_feedback(self) -> str | None:
        """
        Displays the feedback input box and waits for user text or an Esc/Fn/blur bypass.
        Returns the entered feedback string if submitted via Enter, or None if cancelled/escaped.
        """
        self.feedback_event.clear()
        self.feedback_cancelled = False
        self.feedback_text = ""
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_("beginFeedback:", None, True)
        self.feedback_event.wait()
        if self.feedback_cancelled:
            return None
        return self.feedback_text

    def _begin_prompt_on_main_thread(self):
        front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        current_pid = NSRunningApplication.currentApplication().processIdentifier()
        if front_app and front_app.processIdentifier() != current_pid:
            self.last_external_app = front_app

        self.candidate_context_label = self._format_app_candidate_label(self.last_external_app)
        self.mode = "prompt"
        self.status_text = "Specify request..."

        self.panel.setIgnoresMouseEvents_(False)
        self.panel.setAlphaValue_(1.0)
        self.panel.orderFrontRegardless()

        curr_app = NSRunningApplication.currentApplication()
        curr_app.activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows
        )
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.panel.makeKeyAndOrderFront_(None)
        self.panel.makeFirstResponder_(self.webview)

        self._push_js_state(clear_input=True, focus_input=True)

        # Start Speech Recognition and activate visual orbit dots
        if self.speech_engine:
            self.speech_engine.start()
        if self.webview:
            self.webview.evaluateJavaScript_completionHandler_(
                "if (window.setListeningActive) window.setListeningActive(true);", None
            )

        self._start_prompt_key_monitor()

    def _start_prompt_key_monitor(self):
        self._stop_prompt_key_monitor()
        fn_flag = getattr(Quartz, "kCGEventFlagMaskSecondaryFn", 0)

        def _handle_event(event):
            is_esc = (event.type() == Quartz.NSKeyDown) and (event.keyCode() == 0x35)
            is_fn = bool(fn_flag and (event.modifierFlags() & fn_flag))
            if is_esc or is_fn:
                self._stop_speech_listening()
                self._handle_cancel_clicked()
            return event

        try:
            self.prompt_key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                Quartz.NSKeyDownMask | Quartz.NSFlagsChangedMask, _handle_event
            )
        except Exception as exc:
            debug_print(f"[HUD] Prompt key monitor setup warning: {exc}", "warning")

    def _stop_prompt_key_monitor(self):
        if self.prompt_key_monitor is not None:
            try:
                NSEvent.removeMonitor_(self.prompt_key_monitor)
            except Exception:
                pass
            self.prompt_key_monitor = None

    def _stop_speech_listening(self):
        if self.speech_engine:
            self.speech_engine.stop()
        if self.webview:
            self.webview.evaluateJavaScript_completionHandler_(
                "if (window.setListeningActive) window.setListeningActive(false);", None
            )

    def _begin_feedback_on_main_thread(self):
        self.mode = "feedback"
        self.status_text = "Enter feedback..."

        self.panel.setIgnoresMouseEvents_(False)
        self.panel.setAlphaValue_(1.0)
        self.panel.orderFrontRegardless()

        curr_app = NSRunningApplication.currentApplication()
        curr_app.activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows
        )
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.panel.makeKeyAndOrderFront_(None)
        self.panel.makeFirstResponder_(self.webview)

        self._push_js_state(clear_input=True, focus_input=True)
        self._start_feedback_key_monitor()

    def _start_feedback_key_monitor(self):
        self._stop_feedback_key_monitor()
        fn_flag = getattr(Quartz, "kCGEventFlagMaskSecondaryFn", 0)

        # 1. Local monitor for Esc and Fn keys when HUD is key window
        def _handle_local_event(event):
            keycode = event.keyCode() if event.type() == Quartz.NSKeyDown else None
            is_esc = keycode == 0x35
            is_fn = bool(fn_flag and (event.modifierFlags() & fn_flag))
            if is_esc or is_fn:
                AppHelper.callAfter(self._handle_feedback_dismiss)
            return event

        try:
            self.feedback_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                Quartz.NSKeyDownMask | Quartz.NSFlagsChangedMask,
                _handle_local_event,
            )
        except Exception as exc:
            debug_print(f"[HUD] Feedback local monitor setup warning: {exc}", "warning")

        # 2. Global monitor for outside clicks or global Esc/Fn
        monitor_start_time = time.time()

        def _handle_global_event(event):
            # Ignore clicks within the first 150ms of activation to prevent swallowing the focus click
            if time.time() - monitor_start_time < 0.15:
                return

            evt_type = event.type()
            if evt_type in (Quartz.NSLeftMouseDown, Quartz.NSRightMouseDown, Quartz.NSOtherMouseDown):
                # Check if mouse click fell outside HUD panel frame
                if self.panel:
                    mouse_loc = NSEvent.mouseLocation()
                    panel_frame = self.panel.frame()
                    if Quartz.NSPointInRect(mouse_loc, panel_frame):
                        return
                AppHelper.callAfter(self._handle_feedback_dismiss)
                return

            keycode = event.keyCode() if evt_type == Quartz.NSKeyDown else None
            is_esc = keycode == 0x35
            is_fn = bool(fn_flag and (event.modifierFlags() & fn_flag))
            if is_esc or is_fn:
                AppHelper.callAfter(self._handle_feedback_dismiss)

        try:
            self.feedback_global_monitor = NSEvent.addGlobalMonitorForEventsMatchingMask_handler_(
                Quartz.NSLeftMouseDownMask
                | Quartz.NSRightMouseDownMask
                | Quartz.NSOtherMouseDownMask
                | Quartz.NSKeyDownMask
                | Quartz.NSFlagsChangedMask,
                _handle_global_event,
            )
        except Exception as exc:
            debug_print(f"[HUD] Feedback global monitor setup warning: {exc}", "warning")

    def _stop_feedback_key_monitor(self):
        if self.feedback_monitor is not None:
            try:
                NSEvent.removeMonitor_(self.feedback_monitor)
            except Exception:
                pass
            self.feedback_monitor = None

        if self.feedback_global_monitor is not None:
            try:
                NSEvent.removeMonitor_(self.feedback_global_monitor)
            except Exception:
                pass
            self.feedback_global_monitor = None

    def _handle_feedback_dismiss(self):
        """Immediately marks feedback as cancelled and hides the panel on blur/escape."""
        if not self.feedback_event.is_set():
            self.feedback_cancelled = True
            self._complete_feedback_submission()

    def _complete_feedback_submission(self):
        self._stop_feedback_key_monitor()
        def _cleanup():
            if self.panel:
                self.panel.setIgnoresMouseEvents_(True)
                self.panel.resignKeyWindow()
            # Immediately hide the visual panel on main thread
            if self.resident:
                self._hide_on_main_thread()
            else:
                self._close_on_main_thread()
            self.feedback_event.set()
        AppHelper.callAfter(_cleanup)

    def _handle_add_context_clicked(self):
        win_num = self.panel.windowNumber() if self.panel else None
        captured = capture_screen_context_exclude_hud(
            hud_window_number=win_num,
            target_app=self.last_external_app,
        )
        if captured:
            desc, img_bytes = captured
            display_label = self.candidate_context_label or desc
            self.added_context_pages.append((display_label, img_bytes))
            debug_print(f"[HUD] Added context page: {display_label}", "data")
            if self.panel:
                NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                self.panel.makeKeyAndOrderFront_(None)
                self.panel.makeFirstResponder_(self.webview)
            self._push_js_state(focus_input=True)

    def _restore_execution_mode_on_main_thread(self):
        if self._refocus_timer:
            try:
                self._refocus_timer.cancel()
            except Exception:
                pass
            self._refocus_timer = None

        self.mode = "loading"
        self.status_text = "Processing..."
        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.resignKeyWindow()

        if self.last_external_app:
            try:
                self.last_external_app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            except Exception:
                pass

    def _handle_cancel_clicked(self):
        self._stop_speech_listening()
        self._stop_prompt_key_monitor()
        self.prompt_cancelled = True
        self._restore_execution_mode_on_main_thread()
        if self.resident:
            self._hide_on_main_thread()
        else:
            self._close_on_main_thread()
        self.prompt_event.set()

    def _handle_send_clicked(self):
        self._stop_speech_listening()
        self._stop_prompt_key_monitor()
        self.prompt_cancelled = False
        self._restore_execution_mode_on_main_thread()
        self._refresh_display()
        self.prompt_event.set()

    def show_for_run(self):
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_("showHUD:", None, True)

    def _show_for_run_on_main_thread(self):
        self.mode = "loading"
        self.status_text = "Processing..."
        self.actions = []
        self.analysis = None
        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.setAlphaValue_(1.0)
            self.panel.orderFrontRegardless()
        self._push_js_state()

    def update(
        self,
        status_text: str | None = None,
        actions: list | None = None,
        analysis: dict | None = None,
        wait: bool = False,
    ):
        payload = {
            "status_text": status_text,
            "actions": actions,
            "analysis": analysis,
        }
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            "applyState:", payload, wait
        )

    def dismiss_instantly(self):
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            "closeHUD:", None, False
        )

    def close_after_delay(self, seconds: float = 2.0):
        def _delayed():
            time.sleep(seconds)
            if self.resident:
                self.hide_instantly()
            else:
                self.dismiss_instantly()

        threading.Thread(target=_delayed, daemon=True).start()

    def hide_after_delay(self, seconds: float = 2.0):
        self.resident = True
        self.close_after_delay(seconds)

    def hide_instantly(self):
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_("hideHUD:", None, False)

    def _render_on_main_thread(self, payload: dict):
        if payload.get("status_text") is not None:
            self.status_text = payload["status_text"]
        if payload.get("actions") is not None:
            self.actions = payload["actions"]
        if payload.get("analysis") is not None:
            self.analysis = payload["analysis"]
        self._refresh_display()

    def _refresh_display(self):
        if not self.panel or not self.webview:
            return

        lines = []
        if not self.actions:
            lines.append("Waiting for action sequence...")
        else:
            lines.append("ACTIONS & REASONING (Press Esc/Fn to abort):")
            for idx, act in enumerate(self.actions, 1):
                state = act.get("state", "pending")
                icon = {
                    "pending": "⏳",
                    "active": "▶️",
                    "done": "✅",
                    "aborted": "🛑",
                }.get(state, "⏳")
                lines.append(f"{icon} [{idx}] action: {act.get('label', '')}")
                if "reasoning" in act:
                    lines.append(f"       reasoning: {act.get('reasoning', '')}")

        lines.append("\n" + "─" * 42 + "\n")
        if self.analysis:
            lines.append("MACRO ANALYSIS SUMMARY:")
            lines.append(f"• End Goal:      {self.analysis.get('EndGoal', 'N/A')}")
            lines.append(f"• Current State: {self.analysis.get('CurrentState', 'N/A')}")
            lines.append(f"• General Steps: {self.analysis.get('GeneralSteps', 'N/A')}")
            lines.append(f"• DoD:           {self.analysis.get('DoD', 'N/A')}")
        else:
            lines.append("MACRO ANALYSIS SUMMARY:\nAnalyzing telemetry & deep DOM...")

        debug_print(f"[HUD] Status: {self.status_text}\n" + "\n".join(lines), "data")

        if self.mode not in ("prompt", "feedback", "hidden"):
            if self.actions and len(self.actions) > 0:
                self.mode = "running"
            else:
                self.mode = "loading"

        self._push_js_state()

    def _close_on_main_thread(self):
        self._stop_speech_listening()
        self._stop_prompt_key_monitor()
        self._stop_feedback_key_monitor()
        if self._refocus_timer:
            try:
                self._refocus_timer.cancel()
            except Exception:
                pass
            self._refocus_timer = None
        if self.panel:
            self.panel.close()
            self.panel = None
        NSApplication.sharedApplication().stop_(None)
        AppHelper.stopEventLoop()

    def _hide_on_main_thread(self):
        self._stop_speech_listening()
        self._stop_prompt_key_monitor()
        self._stop_feedback_key_monitor()
        if self._refocus_timer:
            try:
                self._refocus_timer.cancel()
            except Exception:
                pass
            self._refocus_timer = None
        self.mode = "hidden"
        self._push_js_state()
        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.setAlphaValue_(0.0)