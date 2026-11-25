"""Upper-right macOS HUD modal for Question and Security Approval prompts.

Can run inside the resident MacroService AppKit process (zero cold-start) or
standalone as a subprocess fallback via `python -m macro_synth.hud.hitl_modal`.
"""

from __future__ import annotations

import json
import sys
import threading
import time
from pathlib import Path
from typing import Any

import objc
import Quartz
import WebKit
from AppKit import (
    NSApplication,
    NSApplicationActivateAllWindows,
    NSApplicationActivateIgnoringOtherApps,
    NSApplicationActivationPolicyAccessory,
    NSBackingStoreBuffered,
    NSColor,
    NSEvent,
    NSEventModifierFlagCommand,
    NSEventModifierFlagControl,
    NSEventModifierFlagOption,
    NSFloatingWindowLevel,
    NSMakeRect,
    NSNotificationCenter,
    NSPanel,
    NSRunningApplication,
    NSScreen,
    NSWindowCollectionBehaviorCanJoinAllSpaces,
    NSWindowCollectionBehaviorFullScreenAuxiliary,
    NSWindowDidResignKeyNotification,
    NSWindowStyleMaskBorderless,
    NSWorkspace,
)
from Foundation import NSObject
from PyObjCTools import AppHelper

from infrastructure.logging import log
from .hud_config import (
    HUD_MARGIN_RIGHT,
    HUD_MARGIN_TOP,
    HUD_POS_X,
    HUD_POS_Y,
    HUD_SCALE,
)
from runtime import (
    BASE_MODAL_HEIGHT,
    BASE_MODAL_WIDTH,
    INPUT_GUARD_SECONDS,
)


def _load_modal_html(scale: float) -> str:
    assets_dir = Path(__file__).resolve().parent / "hud_assets"
    html_template = (assets_dir / "modal.html").read_text(encoding="utf-8")
    css_content = (assets_dir / "modal.css").read_text(encoding="utf-8")
    js_content = (assets_dir / "modal.js").read_text(encoding="utf-8")
    return (
        html_template.replace("__HUD_SCALE__", str(scale))
        .replace("__MODAL_CSS__", css_content)
        .replace("__MODAL_JS__", js_content)
    )


class HitlModalPanel(NSPanel):
    def canBecomeKeyWindow(self):
        return True

    def canBecomeMainWindow(self):
        return True

    def resignKeyWindow(self):
        objc.super(HitlModalPanel, self).resignKeyWindow()
        if hasattr(self, "modal_ref") and self.modal_ref:
            AppHelper.callAfter(self.modal_ref._on_panel_resigned_key)


class ModalScriptMessageHandler(NSObject):
    def initWithModal_(self, modal):
        self = objc.super(ModalScriptMessageHandler, self).init()
        if self is None:
            return None
        self.modal = modal
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        try:
            body = message.body()
            data = json.loads(body) if isinstance(body, str) else dict(body)
            self.modal._handle_js_message(data)
        except Exception as exc:
            log(f"[HitlModal] JS message handling error: {exc}", "warning")


class ModalNavigationDelegate(NSObject):
    def initWithModal_(self, modal):
        self = objc.super(ModalNavigationDelegate, self).init()
        if self is None:
            return None
        self.modal = modal
        return self

    def webView_didFinishNavigation_(self, webview, navigation):
        self.modal._on_webview_ready()


class ModalDispatcher(NSObject):
    def initWithModal_(self, modal):
        self = objc.super(ModalDispatcher, self).init()
        if self is None:
            return None
        self.modal = modal
        return self

    def showPrompt_(self, payload):
        self.modal._show_prompt_on_main_thread(payload)

    def dismissActive_(self, reason):
        self.modal._dismiss_active_on_main_thread(str(reason) if reason else "cancel")


class HitlModalHUD:
    """Upper-right floating WKWebView modal matching MacroHUD's location and theme."""

    def __init__(
        self,
        *,
        resident: bool = True,
        scale: float = HUD_SCALE,
        pos_x: float | None = HUD_POS_X,
        pos_y: float | None = HUD_POS_Y,
        on_complete: Any = None,
    ) -> None:
        self.resident = resident
        self.scale = float(scale)
        self.pos_x = pos_x
        self.pos_y = pos_y
        self._on_complete = on_complete
        self.width = int(round(BASE_MODAL_WIDTH * self.scale))
        self.height = int(round(BASE_MODAL_HEIGHT * self.scale))

        self.panel: Any = None
        self.webview: Any = None
        self.script_handler: Any = None
        self.nav_delegate: Any = None
        self.dispatcher: Any = ModalDispatcher.alloc().initWithModal_(self)

        self._webview_ready = False
        self._pending_js_payload: dict[str, Any] | None = None
        self._active = False
        self._active_blocker_id: str | None = None
        self._active_blocker_type: str = "Question"
        self._active_options: list[dict[str, Any]] = []
        self._input_ready_at: float = 0.0
        self._key_monitor: Any = None
        self._refocus_timer: threading.Timer | None = None
        self._last_external_app: Any = None

        self._response_event = threading.Event()
        self._response_payload: dict[str, Any] = {"action": "cancel", "value": ""}

    def setup_window(self) -> None:
        """Must be called on the AppKit main thread."""
        app = NSApplication.sharedApplication()
        app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)

        ws_nc = NSWorkspace.sharedWorkspace().notificationCenter()
        ws_nc.addObserverForName_object_queue_usingBlock_(
            "NSWorkspaceDidActivateApplicationNotification",
            None,
            None,
            self._on_app_activated,
        )

        x, y = self._compute_window_origin(self.height)
        self.panel = HitlModalPanel.alloc().initWithContentRect_styleMask_backing_defer_(
            NSMakeRect(x, y, self.width, self.height),
            NSWindowStyleMaskBorderless,
            NSBackingStoreBuffered,
            False,
        )
        self.panel.modal_ref = self
        self.panel.setLevel_(NSFloatingWindowLevel)
        self.panel.setFloatingPanel_(True)
        self.panel.setBecomesKeyOnlyIfNeeded_(False)
        self.panel.setHidesOnDeactivate_(False)
        self.panel.setOpaque_(False)
        self.panel.setAlphaValue_(0.0)
        self.panel.setBackgroundColor_(NSColor.clearColor())
        self.panel.setHasShadow_(False)
        self.panel.setIgnoresMouseEvents_(True)
        self.panel.setCollectionBehavior_(
            NSWindowCollectionBehaviorCanJoinAllSpaces
            | NSWindowCollectionBehaviorFullScreenAuxiliary
        )

        NSNotificationCenter.defaultCenter().addObserverForName_object_queue_usingBlock_(
            NSWindowDidResignKeyNotification,
            self.panel,
            None,
            lambda note: AppHelper.callAfter(self._on_panel_resigned_key),
        )

        config = WebKit.WKWebViewConfiguration.alloc().init()
        user_controller = WebKit.WKUserContentController.alloc().init()
        self.script_handler = ModalScriptMessageHandler.alloc().initWithModal_(self)
        user_controller.addScriptMessageHandler_name_(self.script_handler, "modalBridge")
        config.setUserContentController_(user_controller)

        self.webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(
            NSMakeRect(0, 0, self.width, self.height),
            config,
        )
        self.webview.setValue_forKey_(False, "drawsBackground")
        self.nav_delegate = ModalNavigationDelegate.alloc().initWithModal_(self)
        self.webview.setNavigationDelegate_(self.nav_delegate)

        html = _load_modal_html(self.scale)
        self.webview.loadHTMLString_baseURL_(html, None)

        self.panel.setContentView_(self.webview)
        self.panel.orderFrontRegardless()

    def _screen_visible_frame(self):
        screen = NSScreen.mainScreen()
        if screen is None:
            screens = NSScreen.screens()
            screen = screens[0] if screens else None
        if screen is None:
            return NSMakeRect(0, 0, 1440, 900)
        return screen.visibleFrame()

    def _max_window_height(self) -> int:
        frame = self._screen_visible_frame()
        return max(220, int(frame.size.height - 2 * HUD_MARGIN_TOP))

    def _compute_window_origin(self, height: int) -> tuple[float, float]:
        frame = self._screen_visible_frame()
        x = (
            float(self.pos_x)
            if self.pos_x is not None
            else frame.origin.x + frame.size.width - self.width - HUD_MARGIN_RIGHT
        )
        y = (
            float(self.pos_y)
            if self.pos_y is not None
            else frame.origin.y + frame.size.height - height - HUD_MARGIN_TOP
        )
        return x, y

    def _resize_window_on_main_thread(self, desired_unscaled_height: float) -> None:
        scaled = int(round(desired_unscaled_height * self.scale))
        max_h = self._max_window_height()
        clamped = max(140, min(scaled, max_h))
        self.height = clamped
        if self.panel:
            x, y = self._compute_window_origin(self.height)
            self.panel.setFrame_display_(NSMakeRect(x, y, self.width, self.height), True)
        if self.webview:
            self.webview.setFrame_(NSMakeRect(0, 0, self.width, self.height))

    def _on_webview_ready(self) -> None:
        self._webview_ready = True
        if self._pending_js_payload is not None:
            payload = self._pending_js_payload
            self._pending_js_payload = None
            self._push_show_js(payload)

    def _push_show_js(self, js_payload: dict[str, Any]) -> None:
        if not self.webview:
            return
        if not self._webview_ready:
            self._pending_js_payload = js_payload
            return
        js_code = f"if (window.showModal) {{ window.showModal({json.dumps(js_payload)}); }}"
        self.webview.evaluateJavaScript_completionHandler_(js_code, None)

    def _normalize_options(
        self, blocker_type: str, raw_options: list[str] | None
    ) -> tuple[list[dict[str, Any]], bool]:
        if blocker_type == "Security":
            return (
                [
                    {"label": "Approve", "value": "approve", "action": "approve", "style": "approve"},
                    {"label": "Deny", "value": "deny", "action": "deny", "style": "deny"},
                ],
                False,
            )
        if blocker_type == "Action":
            return (
                [{"label": "Resume", "value": "resume", "action": "resume", "style": "approve"}],
                False,
            )
        cleaned = [
            str(opt)
            for opt in (raw_options or [])
            if str(opt).strip() and str(opt).strip().lower() != "other"
        ]
        return (
            [{"label": opt, "value": opt, "action": "answer"} for opt in cleaned],
            True,
        )

    def prompt_sync(self, request: dict[str, Any]) -> dict[str, Any]:
        """Blocking call (from a background thread) that shows the modal and waits for answer."""
        self._response_event.clear()
        self._response_payload = {"action": "cancel", "value": ""}
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            "showPrompt:", request, True
        )
        self._response_event.wait()
        return dict(self._response_payload)

    def cancel_if_active(self, blocker_id: str | None = None, reason: str = "cancelled_externally") -> bool:
        """Dismisses the modal if it is currently showing `blocker_id` (or any if None)."""
        if not self._active:
            return False
        if blocker_id and self._active_blocker_id != blocker_id:
            return False
        self.dispatcher.performSelectorOnMainThread_withObject_waitUntilDone_(
            "dismissActive:", reason, False
        )
        return True

    def _show_prompt_on_main_thread(self, request: dict[str, Any]) -> None:
        front_app = NSWorkspace.sharedWorkspace().frontmostApplication()
        current_pid = NSRunningApplication.currentApplication().processIdentifier()
        if front_app and front_app.processIdentifier() != current_pid:
            self._last_external_app = front_app

        blocker_type = str(request.get("blocker_type") or "Question")
        self._active_blocker_id = str(request.get("blocker_id") or "")
        self._active_blocker_type = blocker_type
        options, allow_other = self._normalize_options(blocker_type, request.get("options"))
        self._active_options = options
        self._active = True
        self._input_ready_at = time.monotonic() + INPUT_GUARD_SECONDS

        max_card_unscaled = max(180, int((self._max_window_height() / self.scale) - 28))
        js_payload = {
            "scale": self.scale,
            "blockerType": blocker_type,
            "agentId": str(request.get("agent_id") or ""),
            "promptText": str(request.get("prompt_text") or ""),
            "commandPreview": str(request.get("command_preview") or ""),
            "options": options,
            "allowOther": allow_other,
            "guardMs": int(INPUT_GUARD_SECONDS * 1000),
            "maxCardHeight": max_card_unscaled,
        }

        if self.panel:
            self.panel.setIgnoresMouseEvents_(False)
            self.panel.setAlphaValue_(1.0)
            self.panel.orderFrontRegardless()

        curr_app = NSRunningApplication.currentApplication()
        curr_app.activateWithOptions_(
            NSApplicationActivateIgnoringOtherApps | NSApplicationActivateAllWindows
        )
        NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
        if self.panel:
            self.panel.makeKeyAndOrderFront_(None)
            self.panel.makeFirstResponder_(self.webview)

        self._push_show_js(js_payload)
        self._start_key_monitor()

    def _start_key_monitor(self) -> None:
        self._stop_key_monitor()

        def _handle_event(event):
            if not self._active:
                return event

            # Ignore all key and mouse input for the first 0.5s after popup
            if time.monotonic() < self._input_ready_at:
                return None

            evt_type = event.type()
            if evt_type != Quartz.NSKeyDown:
                return event

            keycode = event.keyCode()
            if keycode == 0x35:  # Esc
                AppHelper.callAfter(lambda: self._finish_with_dismiss())
                return None

            flags = event.modifierFlags()
            has_cmd = bool(flags & NSEventModifierFlagCommand)
            has_ctrl_or_alt = bool(flags & (NSEventModifierFlagControl | NSEventModifierFlagOption))
            if has_cmd and not has_ctrl_or_alt:
                chars = str(event.charactersIgnoringModifiers() or "")
                if len(chars) == 1 and "1" <= chars <= "9":
                    idx = int(chars) - 1
                    if 0 <= idx < len(self._active_options):
                        chosen = self._active_options[idx]
                        AppHelper.callAfter(
                            lambda c=chosen: self._finish_with_result(
                                c.get("action", "answer"), c.get("value", "")
                            )
                        )
                        return None

            return event

        try:
            mask = (
                Quartz.NSKeyDownMask
                | Quartz.NSLeftMouseDownMask
                | Quartz.NSRightMouseDownMask
                | Quartz.NSOtherMouseDownMask
            )
            self._key_monitor = NSEvent.addLocalMonitorForEventsMatchingMask_handler_(
                mask, _handle_event
            )
        except Exception as exc:
            log(f"[HitlModal] Key monitor setup warning: {exc}", "warning")

    def _stop_key_monitor(self) -> None:
        if self._key_monitor is not None:
            try:
                NSEvent.removeMonitor_(self._key_monitor)
            except Exception:
                pass
            self._key_monitor = None

    def _schedule_refocus(self, delay: float = 0.15) -> None:
        if self._refocus_timer:
            try:
                self._refocus_timer.cancel()
            except Exception:
                pass

        def _do_refocus():
            if not self._active:
                return

            def _main_refocus():
                if self._active and self.panel and self.webview:
                    NSApplication.sharedApplication().activateIgnoringOtherApps_(True)
                    self.panel.makeKeyAndOrderFront_(None)
                    self.panel.makeFirstResponder_(self.webview)
                    if time.monotonic() >= self._input_ready_at:
                        self.webview.evaluateJavaScript_completionHandler_(
                            "if (window.focusOtherInput) window.focusOtherInput();",
                            None,
                        )

            AppHelper.callAfter(_main_refocus)

        self._refocus_timer = threading.Timer(delay, _do_refocus)
        self._refocus_timer.daemon = True
        self._refocus_timer.start()

    def _on_panel_resigned_key(self) -> None:
        if self._active:
            self._schedule_refocus(0.15)

    def _on_app_activated(self, notification) -> None:
        try:
            app = notification.userInfo().objectForKey_("NSWorkspaceApplicationKey")
            current_pid = NSRunningApplication.currentApplication().processIdentifier()
            if app and app.processIdentifier() != current_pid:
                self._last_external_app = app
                if self._active:
                    self._schedule_refocus(0.15)
        except Exception:
            pass

    def _handle_js_message(self, data: dict[str, Any]) -> None:
        msg_type = data.get("type")
        if msg_type == "resize":
            height = data.get("height")
            if isinstance(height, (int, float)):
                self._resize_window_on_main_thread(float(height))
            return

        if not self._active or time.monotonic() < self._input_ready_at:
            return

        if msg_type == "select_option":
            action = str(data.get("action") or "answer")
            value = str(data.get("value") or "")
            self._finish_with_result(action, value)
        elif msg_type == "submit_other":
            value = str(data.get("value") or "").strip()
            if value:
                self._finish_with_result("answer", value)
        elif msg_type == "dismiss":
            self._finish_with_dismiss()

    def _finish_with_dismiss(self) -> None:
        if self._active_blocker_type == "Security":
            self._finish_with_result("deny", "")
        else:
            self._finish_with_result("cancel", "")

    def _dismiss_active_on_main_thread(self, reason: str) -> None:
        if not self._active:
            return
        self._finish_with_result(reason, "")

    def _finish_with_result(self, action: str, value: str) -> None:
        if not self._active:
            return
        self._active = False
        self._active_blocker_id = None
        self._stop_key_monitor()

        if self._refocus_timer:
            try:
                self._refocus_timer.cancel()
            except Exception:
                pass
            self._refocus_timer = None

        if self.webview:
            self.webview.evaluateJavaScript_completionHandler_(
                "if (window.hideModal) window.hideModal();", None
            )

        if self.panel:
            self.panel.setIgnoresMouseEvents_(True)
            self.panel.resignKeyWindow()
            self.panel.setAlphaValue_(0.0)

        if self._last_external_app:
            try:
                self._last_external_app.activateWithOptions_(
                    NSApplicationActivateIgnoringOtherApps
                )
            except Exception:
                pass

        self._response_payload = {"action": action, "value": value}
        self._response_event.set()

        if self._on_complete is not None:
            try:
                self._on_complete(dict(self._response_payload))
            except Exception:
                pass

        if not self.resident:
            if self.panel:
                self.panel.close()
                self.panel = None
            NSApplication.sharedApplication().stop_(None)
            AppHelper.stopEventLoop()


def _run_standalone_cli() -> None:
    """Subprocess fallback entrypoint: reads JSON request from stdin, writes JSON response to stdout."""
    raw = sys.stdin.read()
    try:
        request = json.loads(raw)
    except json.JSONDecodeError as exc:
        print(json.dumps({"action": "cancel", "value": f"Invalid request: {exc}"}), flush=True)
        sys.exit(1)

    emitted = {"done": False}

    def _emit_result(res: dict[str, Any]) -> None:
        if not emitted["done"]:
            emitted["done"] = True
            print(json.dumps(res), flush=True)

    modal = HitlModalHUD(resident=False, on_complete=_emit_result)
    modal.setup_window()

    def _worker():
        modal.prompt_sync(request)

    threading.Thread(target=_worker, daemon=True).start()
    NSApplication.sharedApplication().run()

    _emit_result(dict(modal._response_payload))


if __name__ == "__main__":
    _run_standalone_cli()
