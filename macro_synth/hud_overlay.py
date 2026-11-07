import threading
import time
import objc
from AppKit import (
    NSApplication,
    NSApplicationActivateAllWindows,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezelStyleRounded,
    NSBezierPath,
    NSButton,
    NSColor,
    NSEvent,
    NSFloatingWindowLevel,
    NSFont,
    NSMakeRect,
    NSPanel,
    NSRunningApplication,
    NSScreen,
    NSScrollView,
    NSTextField,
    NSTextView,
    NSView,
    NSWorkspace,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
)
from Foundation import NSObject
import Quartz
from PyObjCTools import AppHelper
from infrastructure.debugging import debug_print
from .context_capture import capture_screen_context_exclude_hud


class InteractiveHUDPanel(NSPanel):
    """
    Borderless NSPanel that can accept key input and mouse clicks when focused
    during the user prompt/feedback phase, and pass clicks through during execution.
    """

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True


class RoundedHUDView(NSView):
    """Custom dark translucent background view with rounded corners and subtle border."""

    def acceptsFirstMouse_(self, event):
        return True

    def drawRect_(self, rect):
        bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.10, 0.11, 0.14, 0.94)
        bg_color.setFill()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 12.0, 12.0)
        path.fill()

        border_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.30, 0.33, 0.40, 0.70)
        border_color.setStroke()
        path.setLineWidth_(1.5)
        path.stroke()


class _PromptFieldDelegate(NSObject):
    """Intercepts Enter (Submit) and Escape (Cancel) inside the HUD prompt text field."""

    def initWithHUD_(self, hud):
        self = objc.super(_PromptFieldDelegate, self).init()
        if self is None:
            return None
        self.hud = hud
        return self

    def control_textView_doCommandBySelector_(self, control, text_view, command_selector):
        selector_str = str(command_selector)
        if selector_str == "insertNewline:":
            self.hud._handle_send_clicked()
            return True
        if selector_str == "cancelOperation:":
            self.hud._handle_cancel_clicked()
            return True
        return False


class _FeedbackFieldDelegate(NSObject):
    """Intercepts Enter (Submit) and Escape (Instant Send) inside the feedback text field."""

    def initWithHUD_(self, hud):
        self = objc.super(_FeedbackFieldDelegate, self).init()
        if self is None:
            return None
        self.hud = hud
        return self

    def control_textView_doCommandBySelector_(self, control, text_view, command_selector):
        selector_str = str(command_selector)
        if selector_str == "insertNewline:":
            self.hud._handle_feedback_submit()
            return True
        if selector_str == "cancelOperation:":
            self.hud._handle_feedback_submit()
            return True
        return False


class _HUDDispatcher(NSObject):
    """Helper NSObject to safely dispatch UI updates and button actions onto the main AppKit thread."""

    def initWithHUD_(self, hud):
        self = objc.super(_HUDDispatcher, self).init()
        if self is None:
            return None
        self.hud = hud
        return self

    def applyState_(self, payload):
        self.hud._render_on_main_thread(payload)

    def closeHUD_(self, _):
        self.hud._close_on_main_thread()

    def hideHUD_(self, _):
        self.hud._hide_on_main_thread()

    def showHUD_(self, _):
        self.hud._show_for_run_on_main_thread()

    def beginPrompt_(self, _):
        self.hud._begin_prompt_on_main_thread()

    def beginFeedback_(self, _):
        self.hud._begin_feedback_on_main_thread()

    @objc.IBAction
    def onAddContextClicked_(self, sender):
        self.hud._handle_add_context_clicked()

    @objc.IBAction
    def onSendClicked_(self, sender):
        self.hud._handle_send_clicked()

    @objc.IBAction
    def onFeedbackSendClicked_(self, sender):
        self.hud._handle_feedback_submit()


class MacroHUD:
    def __init__(self, width: int = 420, height: int = 140, resident: bool = False):
        self.width = width
        self.height = height
        self.resident = resident
        self.panel = None
        self.content_view = None
        self.scroll_view = None
        self.status_label = None
        self.body_text_view = None

        # Interactive Prompt Phase Controls
        self.prompt_container = None
        self.input_field = None
        self.send_button = None
        self.add_context_button = None
        self.context_list_scroll = None
        self.context_list_view = None

        # Post-Execution Feedback Controls
        self.feedback_container = None
        self.feedback_input_field = None
        self.feedback_send_button = None
        self.feedback_monitor = None

        self.dispatcher = _HUDDispatcher.alloc().initWithHUD_(self)
        self.field_delegate = _PromptFieldDelegate.alloc().initWithHUD_(self)
        self.feedback_delegate = _FeedbackFieldDelegate.alloc().initWithHUD_(self)

        self.status_text = "Initializing..."
        self.actions = []
        self.analysis = None

        # Synchronization for Interactive Prompt Phase
        self.prompt_event = threading.Event()
        self.prompt_cancelled = False
        self.user_request_text = ""
        self.added_context_pages = []
        self.last_external_app = None

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

        screen_frame = NSScreen.mainScreen().visibleFrame()
        margin = 20.0
        x = screen_frame.origin.x + screen_frame.size.width - self.width - margin
        y = screen_frame.origin.y + screen_frame.size.height - self.height - margin

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
        self.panel.setHasShadow_(True)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        self.content_view = RoundedHUDView.alloc().initWithFrame_(NSMakeRect(0, 0, self.width, self.height))
        self.panel.setContentView_(self.content_view)

        # Header Status Label
        self.status_label = NSTextField.alloc().initWithFrame_(
            NSMakeRect(12, self.height - 28, self.width - 24, 18)
        )
        self.status_label.setEditable_(False)
        self.status_label.setBezeled_(False)
        self.status_label.setDrawsBackground_(False)
        self.status_label.setTextColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.40, 0.85, 1.0, 1.0)
        )
        self.status_label.setFont_(NSFont.boldSystemFontOfSize_(12.5))
        self.status_label.setStringValue_("⚡ Macro Synth: Initializing...")
        self.content_view.addSubview_(self.status_label)

        # Scrollable Monospace Body Area for Execution Mode
        self.scroll_view = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(12, 10, self.width - 24, self.height - 40)
        )
        self.scroll_view.setDrawsBackground_(False)
        self.scroll_view.setHasVerticalScroller_(False)
        self.scroll_view.setHasHorizontalScroller_(False)

        self.body_text_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, self.width - 24, self.height - 40)
        )
        self.body_text_view.setEditable_(False)
        self.body_text_view.setSelectable_(False)
        self.body_text_view.setDrawsBackground_(False)
        self.body_text_view.setTextColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.92, 0.93, 0.96, 1.0)
        )
        self.body_text_view.setFont_(NSFont.monospacedSystemFontOfSize_weight_(11.0, 0.0))

        self.scroll_view.setDocumentView_(self.body_text_view)
        self.content_view.addSubview_(self.scroll_view)

        # Build Interactive Prompt & Feedback Containers
        self._setup_prompt_views()
        self._setup_feedback_views()

        self.panel.orderFrontRegardless()
        self._refresh_display()

    def _on_app_activated(self, notification):
        try:
            app = notification.userInfo().objectForKey_("NSWorkspaceApplicationKey")
            current_pid = NSRunningApplication.currentApplication().processIdentifier()
            if app and app.processIdentifier() != current_pid:
                self.last_external_app = app
        except Exception:
            pass

    def _setup_prompt_views(self):
        prompt_h = 168
        self.prompt_container = NSView.alloc().initWithFrame_(NSMakeRect(12, 10, self.width - 24, prompt_h))
        self.prompt_container.setHidden_(True)
        inner_w = self.width - 24

        send_w = 58
        self.input_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(0, prompt_h - 28, inner_w - send_w - 6, 24)
        )
        self.input_field.setPlaceholderString_("Optional request (Enter to send, Esc to cancel)...")
        self.input_field.setFont_(NSFont.systemFontOfSize_(12.0))
        self.input_field.setBezeled_(True)
        self.input_field.setDrawsBackground_(True)
        self.input_field.setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.18, 0.22, 1.0)
        )
        self.input_field.setTextColor_(NSColor.whiteColor())
        self.input_field.setDelegate_(self.field_delegate)
        self.prompt_container.addSubview_(self.input_field)

        self.send_button = NSButton.alloc().initWithFrame_(
            NSMakeRect(inner_w - send_w, prompt_h - 29, send_w, 26)
        )
        self.send_button.setTitle_("Send")
        self.send_button.setBezelStyle_(NSBezelStyleRounded)
        self.send_button.setTarget_(self.dispatcher)
        self.send_button.setAction_("onSendClicked:")
        self.prompt_container.addSubview_(self.send_button)

        self.add_context_button = NSButton.alloc().initWithFrame_(
            NSMakeRect(0, prompt_h - 60, inner_w, 26)
        )
        self.add_context_button.setTitle_("+ Add this page to context")
        self.add_context_button.setBezelStyle_(NSBezelStyleRounded)
        self.add_context_button.setTarget_(self.dispatcher)
        self.add_context_button.setAction_("onAddContextClicked:")
        self.prompt_container.addSubview_(self.add_context_button)

        list_h = prompt_h - 68
        self.context_list_scroll = NSScrollView.alloc().initWithFrame_(
            NSMakeRect(0, 0, inner_w, list_h)
        )
        self.context_list_scroll.setDrawsBackground_(False)
        self.context_list_scroll.setHasVerticalScroller_(True)

        self.context_list_view = NSTextView.alloc().initWithFrame_(
            NSMakeRect(0, 0, inner_w, list_h)
        )
        self.context_list_view.setEditable_(False)
        self.context_list_view.setSelectable_(False)
        self.context_list_view.setDrawsBackground_(False)
        self.context_list_view.setTextColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.80, 0.84, 0.90, 1.0)
        )
        self.context_list_view.setFont_(NSFont.monospacedSystemFontOfSize_weight_(10.5, 0.0))
        self.context_list_scroll.setDocumentView_(self.context_list_view)
        self.prompt_container.addSubview_(self.context_list_scroll)

        self.content_view.addSubview_(self.prompt_container)

    def _setup_feedback_views(self):
        feedback_h = 36
        inner_w = self.width - 24
        self.feedback_container = NSView.alloc().initWithFrame_(NSMakeRect(12, 10, inner_w, feedback_h))
        self.feedback_container.setHidden_(True)

        send_w = 58
        self.feedback_input_field = NSTextField.alloc().initWithFrame_(
            NSMakeRect(0, 4, inner_w - send_w - 6, 26)
        )
        self.feedback_input_field.setPlaceholderString_("Optional feedback (Esc/Fn/Enter to send)...")
        self.feedback_input_field.setFont_(NSFont.systemFontOfSize_(12.0))
        self.feedback_input_field.setBezeled_(True)
        self.feedback_input_field.setDrawsBackground_(True)
        self.feedback_input_field.setBackgroundColor_(
            NSColor.colorWithCalibratedRed_green_blue_alpha_(0.16, 0.18, 0.22, 1.0)
        )
        self.feedback_input_field.setTextColor_(NSColor.whiteColor())
        self.feedback_input_field.setDelegate_(self.feedback_delegate)
        self.feedback_container.addSubview_(self.feedback_input_field)

        self.feedback_send_button = NSButton.alloc().initWithFrame_(
            NSMakeRect(inner_w - send_w, 3, send_w, 28)
        )
        self.feedback_send_button.setTitle_("Send")
        self.feedback_send_button.setBezelStyle_(NSBezelStyleRounded)
        self.feedback_send_button.setTarget_(self.dispatcher)
        self.feedback_send_button.setAction_("onFeedbackSendClicked:")
        self.feedback_container.addSubview_(self.feedback_send_button)

        self.content_view.addSubview_(self.feedback_container)

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

        self.status_text = "Specify Request"
        self.status_label.setStringValue_(f"⚡ {self.status_text}")

        target_h = 214
        self._resize_panel_top_right(target_h)

        self.scroll_view.setHidden_(True)
        self.feedback_container.setHidden_(True)
        self.prompt_container.setHidden_(False)
        self.input_field.setStringValue_("")
        self._refresh_context_list_text()

        self.panel.setIgnoresMouseEvents_(False)
        self.panel.setAlphaValue_(1.0)
        self.panel.orderFrontRegardless()

        curr_app = NSRunningApplication.currentApplication()
        curr_app.activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows
        )
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.panel.makeKeyAndOrderFront_(None)
        self.panel.makeFirstResponder_(self.input_field)
        self.input_field.selectText_(None)

    def _begin_feedback_on_main_thread(self):
        self.status_text = "Execution Complete — Feedback?"
        self.status_label.setStringValue_(f"⚡ {self.status_text}")

        target_h = 82
        self._resize_panel_top_right(target_h)

        self.scroll_view.setHidden_(True)
        self.prompt_container.setHidden_(True)
        self.feedback_container.setHidden_(False)
        self.feedback_input_field.setStringValue_("")

        self.panel.setIgnoresMouseEvents_(False)
        self.panel.setAlphaValue_(1.0)
        self.panel.orderFrontRegardless()

        curr_app = NSRunningApplication.currentApplication()
        curr_app.activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows
        )
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        self.panel.makeKeyAndOrderFront_(None)
        self.panel.makeFirstResponder_(self.feedback_input_field)
        self.feedback_input_field.selectText_(None)

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
        self._stop_feedback_key_monitor()
        if self.feedback_input_field:
            self.feedback_text = str(self.feedback_input_field.stringValue() or "").strip()
        else:
            self.feedback_text = ""
        self.feedback_container.setHidden_(True)
        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.resignKeyWindow()
        self.feedback_event.set()

    def _refresh_context_list_text(self):
        if not self.context_list_view:
            return
        if not self.added_context_pages:
            self.context_list_view.setString_("Added context pages: (none)\n")
        else:
            lines = [f"Added context pages ({len(self.added_context_pages)}):"]
            for i, (desc, _) in enumerate(self.added_context_pages, 1):
                lines.append(f"  {i}. {desc}")
            self.context_list_view.setString_("\n".join(lines))

    def _handle_add_context_clicked(self):
        win_num = self.panel.windowNumber() if self.panel else None
        captured = capture_screen_context_exclude_hud(win_num)
        if captured:
            self.added_context_pages.append(captured)
            self._refresh_context_list_text()
            self.status_label.setStringValue_(f"⚡ Added: {captured[0]}")
        if self.panel and self.input_field:
            self.panel.makeFirstResponder_(self.input_field)
            self.input_field.selectText_(None)

    def _restore_execution_mode_on_main_thread(self):
        self.prompt_container.setHidden_(True)
        self.feedback_container.setHidden_(True)
        self.scroll_view.setHidden_(False)
        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.resignKeyWindow()

        if self.last_external_app:
            try:
                self.last_external_app.activateWithOptions_(NSApplicationActivateIgnoringOtherApps)
            except Exception:
                pass

    def _handle_send_clicked(self):
        self.user_request_text = str(self.input_field.stringValue() or "").strip()
        self.prompt_cancelled = False
        self._restore_execution_mode_on_main_thread()
        self.status_text = "Parsing actions..."
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

    def _resize_panel_top_right(self, new_height: int):
        if not self.panel:
            return
        current_frame = self.panel.frame()
        old_height = current_frame.size.height
        old_y = current_frame.origin.y
        x = current_frame.origin.x
        w = current_frame.size.width
        new_y = old_y + old_height - new_height

        self.panel.setFrame_display_(NSMakeRect(x, new_y, w, new_height), True)
        if self.content_view:
            self.content_view.setFrame_(NSMakeRect(0, 0, w, new_height))
        if self.status_label:
            self.status_label.setFrame_(NSMakeRect(12, new_height - 24, w - 24, 18))
        if self.prompt_container:
            self.prompt_container.setFrame_(NSMakeRect(12, 10, w - 24, new_height - 38))
        if self.feedback_container:
            self.feedback_container.setFrame_(NSMakeRect(12, 10, w - 24, new_height - 38))

    def show_for_run(self):
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_("showHUD:", None, True)

    def _show_for_run_on_main_thread(self):
        self.status_text = "Capturing DOM & recent telemetry..."
        self.actions = []
        self.analysis = None
        if self.prompt_container:
            self.prompt_container.setHidden_(True)
        if self.feedback_container:
            self.feedback_container.setHidden_(True)
        if self.scroll_view:
            self.scroll_view.setHidden_(False)
        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.setAlphaValue_(1.0)
            self.panel.orderFrontRegardless()
        if self.status_label:
            self.status_label.setStringValue_(f"⚡ {self.status_text}")
        if self.body_text_view:
            self.body_text_view.setString_("Preparing macro context...")

    def update(self, status_text: str | None = None, actions: list | None = None, analysis: dict | None = None, wait: bool = False):
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
        if not self.status_label or not self.body_text_view or not self.panel:
            return

        self.status_label.setStringValue_(f"⚡ {self.status_text}")

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
                lines.append(f"{icon} [{idx}] action: {act['label']}")
                lines.append(f"       reasoning: {act['reasoning']}")

        lines.append("\n" + "─" * 42 + "\n")
        if self.analysis:
            lines.append("MACRO ANALYSIS SUMMARY:")
            lines.append(f"• End Goal:      {self.analysis.get('EndGoal', 'N/A')}")
            lines.append(f"• Current State: {self.analysis.get('CurrentState', 'N/A')}")
            lines.append(f"• General Steps: {self.analysis.get('GeneralSteps', 'N/A')}")
            lines.append(f"• DoD:           {self.analysis.get('DoD', 'N/A')}")
        else:
            lines.append("MACRO ANALYSIS SUMMARY:\nAnalyzing telemetry & deep DOM...")

        text_content = "\n".join(lines)
        debug_print(f"[HUD] Status: {self.status_text}\n{text_content}", "data")
        self.body_text_view.setString_(text_content)

        layout_manager = self.body_text_view.layoutManager()
        text_container = self.body_text_view.textContainer()
        layout_manager.ensureLayoutForTextContainer_(text_container)
        used_rect = layout_manager.usedRectForTextContainer_(text_container)
        text_height = max(30, used_rect.size.height + 8)

        header_height = 26
        spacing = 6
        padding_y = 20
        new_height = int(header_height + spacing + text_height + padding_y)

        screen_frame = NSScreen.mainScreen().visibleFrame()
        max_height = int(screen_frame.size.height * 0.8)
        new_height = max(90, min(new_height, max_height))

        current_frame = self.panel.frame()
        old_height = current_frame.size.height
        old_y = current_frame.origin.y
        x = current_frame.origin.x
        w = current_frame.size.width
        new_y = old_y + old_height - new_height

        new_frame = NSMakeRect(x, new_y, w, new_height)
        self.panel.setFrame_display_(new_frame, True)

        if self.content_view:
            self.content_view.setFrame_(NSMakeRect(0, 0, w, new_height))
        if self.status_label:
            self.status_label.setFrame_(NSMakeRect(12, new_height - 24, w - 24, 18))
        if self.scroll_view:
            self.scroll_view.setFrame_(NSMakeRect(12, 10, w - 24, new_height - 38))
        if self.body_text_view:
            self.body_text_view.setFrame_(NSMakeRect(0, 0, w - 24, max(text_height, new_height - 38)))

    def _close_on_main_thread(self):
        self._stop_feedback_key_monitor()
        if self.panel:
            self.panel.close()
            self.panel = None
        NSApplication.sharedApplication().stop_(None)
        AppHelper.stopEventLoop()

    def _hide_on_main_thread(self):
        self._stop_feedback_key_monitor()
        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.setAlphaValue_(0.0)