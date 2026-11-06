import objc
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSFloatingWindowLevel,
    NSFont,
    NSMakeRect,
    NSPanel,
    NSScreen,
    NSScrollView,
    NSTextField,
    NSTextView,
    NSView,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowStyleMaskBorderless,
    NSWindowStyleMaskNonactivatingPanel,
)
from Foundation import NSObject, NSRunLoop, NSDate
from PyObjCTools import AppHelper
from infrastructure.debugging import debug_print


class RoundedHUDView(NSView):
    """Custom dark translucent background view with rounded corners and subtle border."""

    def drawRect_(self, rect):
        # Deep charcoal background with 92% opacity
        bg_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.10, 0.11, 0.14, 0.92)
        bg_color.setFill()
        path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(self.bounds(), 12.0, 12.0)
        path.fill()

        # Subtle crisp border
        border_color = NSColor.colorWithCalibratedRed_green_blue_alpha_(0.30, 0.33, 0.40, 0.70)
        border_color.setStroke()
        path.setLineWidth_(1.5)
        path.stroke()


class _HUDDispatcher(NSObject):
    """Helper NSObject to safely dispatch UI updates onto the main AppKit thread."""

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
        self.dispatcher = _HUDDispatcher.alloc().initWithHUD_(self)

        self.status_text = "Initializing..."
        self.actions = []       # List of dicts: {"label": str, "reasoning": str, "state": "pending"|"active"|"done"|"aborted"}
        self.analysis = None    # Dict with EndGoal, CurrentState, GeneralSteps, DoD

    def setup_window(self):
        """Must be called on the main thread before starting the worker thread."""
        app = NSApplication.sharedApplication()
        # Accessory policy prevents a Dock icon or menu bar from stealing active window focus
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        screen_frame = NSScreen.mainScreen().visibleFrame()
        margin = 20.0
        x = screen_frame.origin.x + screen_frame.size.width - self.width - margin
        y = screen_frame.origin.y + screen_frame.size.height - self.height - margin

        style_mask = NSWindowStyleMaskBorderless | NSWindowStyleMaskNonactivatingPanel
        self.panel = NSPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, self.width, self.height),
            style_mask,
            NSBackingStoreBuffered,
            False,
        )

        # Float above all apps (including full-screen spaces) without activating or intercepting clicks
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setFloatingPanel_(True)
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

        # Thinner Header Status Label
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

        # Scrollable Monospace Body Area for Actions + Separator + Macro Analysis
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

        self.panel.orderFrontRegardless()
        self._refresh_display()

    def show_for_run(self):
        """Reset and show a reusable HUD for the next resident run."""
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_("showHUD:", None, True)

    def _show_for_run_on_main_thread(self):
        self.status_text = "Capturing DOM & recent telemetry..."
        self.actions = []
        self.analysis = None
        if self.panel:
            self.panel.setAlphaValue_(1.0)
            self.panel.orderFrontRegardless()
        if self.status_label:
            self.status_label.setStringValue_(f"⚡ {self.status_text}")
        if self.body_text_view:
            self.body_text_view.setString_("Preparing macro context...")

    def update(self, status_text: str | None = None, actions: list | None = None, analysis: dict | None = None):
        """Thread-safe method called from background worker thread to update the HUD."""
        payload = {
            "status_text": status_text,
            "actions": actions,
            "analysis": analysis,
        }
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            "applyState:", payload, False
        )

    def dismiss_instantly(self):
        """Immediately closes the window and terminates the run loop without waiting."""
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            "closeHUD:", None, False
        )

    def close_after_delay(self, seconds: float = 2.0):
        """Close one-shot HUDs or hide resident HUDs after a delay."""
        import threading
        def _delayed():
            import time
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
        # 1. Actions List Section
        if not self.actions:
            lines.append("Waiting for action sequence...")
        else:
            lines.append("ACTIONS & REASONING (Press ANY key to abort):")
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

        # 2. Separator Bar
        lines.append("\n" + "─" * 42 + "\n")
        # 3. Macro Analysis Summary Section
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

        # Dynamically measure exact text height required for current content
        layout_manager = self.body_text_view.layoutManager()
        text_container = self.body_text_view.textContainer()
        layout_manager.ensureLayoutForTextContainer_(text_container)
        used_rect = layout_manager.usedRectForTextContainer_(text_container)
        text_height = max(30, used_rect.size.height + 8)

        # Compute new window height (Header ~26px + spacing + text_height + padding)
        header_height = 26
        spacing = 6
        padding_y = 20
        new_height = int(header_height + spacing + text_height + padding_y)

        # Clamp height between 90px and 80% of screen height
        screen_frame = NSScreen.mainScreen().visibleFrame()
        max_height = int(screen_frame.size.height * 0.8)
        new_height = max(90, min(new_height, max_height))

        # Update panel frame while keeping top-right corner anchored
        current_frame = self.panel.frame()
        old_height = current_frame.size.height
        old_y = current_frame.origin.y
        x = current_frame.origin.x
        w = current_frame.size.width

        # Top edge remains constant: old_y + old_height = new_y + new_height
        new_y = old_y + old_height - new_height

        new_frame = NSMakeRect(x, new_y, w, new_height)
        self.panel.setFrame_display_(new_frame, True)

        # Resize subviews to fit new bounds cleanly
        if self.content_view:
            self.content_view.setFrame_(NSMakeRect(0, 0, w, new_height))
        if self.status_label:
            self.status_label.setFrame_(NSMakeRect(12, new_height - 24, w - 24, 18))
        if self.scroll_view:
            self.scroll_view.setFrame_(NSMakeRect(12, 10, w - 24, new_height - 38))
        if self.body_text_view:
            self.body_text_view.setFrame_(NSMakeRect(0, 0, w - 24, max(text_height, new_height - 38)))

    def _close_on_main_thread(self):
        if self.panel:
            self.panel.close()
            self.panel = None
        AppHelper.stopEventLoop()

    def _hide_on_main_thread(self):
        if self.panel:
            self.panel.setAlphaValue_(0.0)