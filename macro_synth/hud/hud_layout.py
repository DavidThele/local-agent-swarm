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
)
import Quartz
import WebKit
from PyObjCTools import AppHelper
from infrastructure.debugging import debug_print
from ..context_capture import capture_screen_context_exclude_hud
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

    def _on_app_activated(self, notification):
        try:
            app = notification.userInfo().objectForKey_("NSWorkspaceApplicationKey")
            current_pid = NSRunningApplication.currentApplication().processIdentifier()
            if app and app.processIdentifier() != current_pid:
                self.last_external_app = app
                self.candidate_context_label = self._format_app_candidate_label(app)
                if self.mode == "prompt":
                    self._push_js_state()
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
        if msg_type == "submit_prompt":
            self.user_request_text = str(data.get("text") or "").strip()
            self._handle_send_clicked()
        elif msg_type == "cancel_prompt":
            self._handle_cancel_clicked()
        elif msg_type == "add_context":
            self._handle_add_context_clicked()
        elif msg_type == "remove_context":
            idx = data.get("index")
            if isinstance(idx, int) and 0 <= idx < len(self.added_context_pages):
                removed = self.added_context_pages.pop(idx)
                debug_print(f"[HUD] Removed context page: {removed[0]}", "data")
                self._push_js_state()
        elif msg_type == "submit_feedback":
            self.feedback_text = str(data.get("text") or "").strip()
            self._complete_feedback_submission()

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

    def wait_for_feedback(self) -> str:
        """
        Displays the feedback input box and waits for user text or an Esc/Fn bypass.
        Returns the entered feedback string.
        """
        self.feedback_event.clear()
        self.feedback_text = ""
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_("beginFeedback:", None, True)
        self.feedback_event.wait()
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

        def _handle_event(event):
            keycode = event.keyCode() if event.type() == Quartz.NSKeyDown else None
            is_esc = keycode == 0x35
            is_fn = bool(fn_flag and (event.modifierFlags() & fn_flag))
            if is_esc or is_fn:
                self._handle_feedback_submit()

        try:
            self.feedback_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                Quartz.NSKeyDownMask | Quartz.NSFlagsChangedMask,
                lambda evt: (_handle_event(evt), evt)[1],
            )
        except Exception as exc:
            debug_print(f"[HUD] Feedback monitor setup warning: {exc}", "warning")

    def _stop_feedback_key_monitor(self):
        if self.feedback_monitor is not None:
            try:
                NSEvent.removeMonitor_(self.feedback_monitor)
            except Exception:
                pass
            self.feedback_monitor = None

    def _handle_feedback_submit(self):
        """Triggered when Esc or Fn is pressed via the native event monitor."""
        if not self.webview:
            self._complete_feedback_submission()
            return

        def _on_eval(val, err):
            if val is not None:
                self.feedback_text = str(val).strip()
            self._complete_feedback_submission()

        self.webview.evaluateJavaScript_completionHandler_(
            "document.getElementById('hud-input') ? document.getElementById('hud-input').value : ''",
            _on_eval,
        )

    def _complete_feedback_submission(self):
        self._stop_feedback_key_monitor()
        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.resignKeyWindow()
        self.feedback_event.set()

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
            self._push_js_state(focus_input=True)

    def _restore_execution_mode_on_main_thread(self):
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

    def _handle_send_clicked(self):
        self.prompt_cancelled = False
        self._restore_execution_mode_on_main_thread()
        self._refresh_display()
        self.prompt_event.set()

    def _handle_cancel_clicked(self):
        self.prompt_cancelled = True
        self._restore_execution_mode_on_main_thread()
        if self.resident:
            self._hide_on_main_thread()
        else:
            self._close_on_main_thread()
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

        # Keep full telemetry/reasoning/analysis logging in debug_print
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

        # Switch between State 2 (Loading) and State 3 (Running Actions) automatically
        if self.mode not in ("prompt", "feedback", "hidden"):
            if self.actions and len(self.actions) > 0:
                self.mode = "running"
            else:
                self.mode = "loading"

        self._push_js_state()

    def _close_on_main_thread(self):
        self._stop_feedback_key_monitor()
        if self.panel:
            self.panel.close()
            self.panel = None
        NSApplication.sharedApplication().stop_(None)
        AppHelper.stopEventLoop()

    def _hide_on_main_thread(self):
        self._stop_feedback_key_monitor()
        self.mode = "hidden"
        self._push_js_state()
        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.setAlphaValue_(0.0)