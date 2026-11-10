import json
import objc
from AppKit import NSPanel
from Foundation import NSObject
from infrastructure.debugging import debug_print

class InteractiveHUDPanel(NSPanel):
    """
    Borderless NSPanel that can accept key input and mouse clicks when focused
    during the user prompt/feedback phase, and pass clicks through during execution.
    """

    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True

    def resignKeyWindow(self):
        objc.super(InteractiveHUDPanel, self).resignKeyWindow()
        if hasattr(self, "hud_ref") and self.hud_ref:
            from PyObjCTools import AppHelper
            AppHelper.callAfter(self.hud_ref._on_panel_resigned_key)

class HUDScriptMessageHandler(NSObject):
    """Bridges JavaScript events from WKWebView back into Python."""

    def initWithHUD_(self, hud):
        self = objc.super(HUDScriptMessageHandler, self).init()
        if self is None:
            return None
        self.hud = hud
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        try:
            body = message.body()
            if isinstance(body, str):
                data = json.loads(body)
            else:
                data = dict(body)
            self.hud._handle_js_message(data)
        except Exception as exc:
            debug_print(f"[HUD] JS message handling error: {exc}", "warning")


class HUDDispatcher(NSObject):
    """Helper NSObject to safely dispatch UI updates onto the main AppKit thread."""

    def initWithHUD_(self, hud):
        self = objc.super(HUDDispatcher, self).init()
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