import argparse
import json
from pathlib import Path
import signal
import threading
import time
import urllib.request
import webbrowser

import objc
import uvicorn
import WebKit
from AppKit import (
    NSApplication,
    NSApplicationActivationPolicyRegular,
    NSBackingStoreBuffered,
    NSBezierPath,
    NSColor,
    NSCompositingOperationSourceOver,
    NSEvent,
    NSEventModifierFlagCommand,
    NSEventModifierFlagShift,
    NSEventTypeApplicationDefined,
    NSGraphicsContext,
    NSImage,
    NSImageInterpolationNone,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSNormalWindowLevel,
    NSScreen,
    NSTerminateCancel,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeSize, NSObject, NSTimer, NSURL, NSURLRequest, NSZeroPoint, NSZeroRect

from infrastructure.logging import log

HOST = "127.0.0.1"
PORT = 8765
REPO_ROOT = Path(__file__).resolve().parent

# Prevent Python GC from collecting Obj-C delegates and message handlers while the UI is alive
_KEEP_ALIVE: list[object] = []
_SIGNAL_RECEIVED = threading.Event()


def _handle_exit_signal(signum, _frame):
    """Records SIGINT/SIGTERM so the active loop (AppKit or --browser) can exit gracefully."""
    _SIGNAL_RECEIVED.set()


def _stop_appkit_run_loop() -> None:
    """Stops NSApplication.run() cleanly without invoking C exit(0)."""
    app = NSApplication.sharedApplication()
    app.stop_(None)
    # Post a dummy event so NSApplication.run() wakes up and returns immediately
    wakeup = NSEvent.otherEventWithType_location_modifierFlags_timestamp_windowNumber_context_subtype_data1_data2_(
        NSEventTypeApplicationDefined,
        NSZeroPoint,
        0,
        0.0,
        0,
        None,
        0,
        0,
        0,
    )
    if wakeup is not None:
        app.postEvent_atStart_(wakeup, True)


class SwarmShutdownController:
    """
    Coordinates idempotent teardown of the AppKit window/WKWebView, Uvicorn server,
    active agents, subprocess groups, and Playwright routers so macOS never crashes
    with 'Python quit unexpectedly'.
    """

    def __init__(self, server: uvicorn.Server | None = None, server_thread: threading.Thread | None = None):
        self.server = server
        self.server_thread = server_thread
        self.window = None
        self.webview = None
        self.content_controller = None
        self.signal_timer = None
        self._ui_torn_down = False
        self._backend_cleaned = False
        self._lock = threading.Lock()

    def attach_ui(self, window, webview, content_controller, signal_timer=None) -> None:
        self.window = window
        self.webview = webview
        self.content_controller = content_controller
        self.signal_timer = signal_timer

    def teardown_ui_and_stop_loop(self) -> None:
        """
        Must be called on the AppKit main thread. Detaches WKWebView script handlers
        and window delegates before stopping the run loop so AppKit never calls C exit(0)
        while Python threads or WebKit IPC are still active.
        """
        with self._lock:
            if self._ui_torn_down:
                return
            self._ui_torn_down = True

        if self.signal_timer is not None:
            try:
                self.signal_timer.invalidate()
            except Exception:
                pass
            self.signal_timer = None

        if self.content_controller is not None:
            try:
                self.content_controller.removeScriptMessageHandlerForName_("windowBridge")
            except Exception:
                pass
            self.content_controller = None

        if self.webview is not None:
            try:
                self.webview.stopLoading()
            except Exception:
                pass

        if self.window is not None:
            try:
                self.window.setDelegate_(None)
            except Exception:
                pass
            try:
                self.window.orderOut_(None)
            except Exception:
                pass
            try:
                self.window.setContentView_(None)
            except Exception:
                pass

        self.webview = None
        self.window = None

        _stop_appkit_run_loop()

    def cleanup_backend(self) -> None:
        """Cancels running agents/subprocesses, closes Playwright/CDP, and joins Uvicorn."""
        with self._lock:
            if self._backend_cleaned:
                return
            self._backend_cleaned = True

        try:
            import swarm_server

            swarm_server.shutdown_runtime(timeout=4.0)
        except Exception as exc:
            log(f"[SwarmGUI] Runtime shutdown warning: {exc}", "warning")

        if self.server is not None:
            self.server.should_exit = True

        if self.server_thread is not None and self.server_thread.is_alive():
            self.server_thread.join(timeout=3.0)
            if self.server_thread.is_alive() and self.server is not None:
                self.server.force_exit = True
                self.server_thread.join(timeout=1.5)

        _KEEP_ALIVE.clear()


def build_acorn_app_icon():
    """Creates a crisp macOS Dock/App Switcher icon from the existing acorn.png sprite."""
    candidates = [
        REPO_ROOT / "swarm-widget-ui" / "public" / "sprites" / "acorn.png",
        REPO_ROOT / "swarm-widget-ui" / "dist" / "sprites" / "acorn.png",
    ]
    icon_path = next((p for p in candidates if p.exists()), None)
    if not icon_path:
        return None

    sprite = NSImage.alloc().initWithContentsOfFile_(str(icon_path))
    if sprite is None:
        return None

    size = 512.0
    canvas = NSImage.alloc().initWithSize_(NSMakeSize(size, size))
    canvas.lockFocus()
    try:
        ctx = NSGraphicsContext.currentContext()
        if ctx:
            ctx.setImageInterpolation_(NSImageInterpolationNone)

        # macOS-style dark squircle background matching the app's monochrome palette
        inset = 36.0
        bg_rect = NSMakeRect(inset, inset, size - inset * 2, size - inset * 2)
        bg_path = NSBezierPath.bezierPathWithRoundedRect_xRadius_yRadius_(bg_rect, 96.0, 96.0)
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.067, 0.067, 0.078, 1.0).setFill()
        bg_path.fill()

        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.22, 0.22, 0.26, 1.0).setStroke()
        bg_path.setLineWidth_(6.0)
        bg_path.stroke()

        # Center and aspect-fit the acorn sprite with generous padding
        src_size = sprite.size()
        if src_size.width > 0 and src_size.height > 0:
            max_dim = size - 192.0
            scale = min(max_dim / src_size.width, max_dim / src_size.height)
            draw_w = src_size.width * scale
            draw_h = src_size.height * scale
            draw_rect = NSMakeRect(
                (size - draw_w) / 2.0,
                (size - draw_h) / 2.0,
                draw_w,
                draw_h,
            )
            sprite.drawInRect_fromRect_operation_fraction_(
                draw_rect,
                NSZeroRect,
                NSCompositingOperationSourceOver,
                1.0,
            )
    finally:
        canvas.unlockFocus()

    return canvas


class SwarmAppDelegate(NSObject):
    """
    Intercepts Cmd+Q, Menu Bar Quit, and Dock Quit so AppKit stops the run loop cleanly
    and returns control to Python instead of calling C exit(0) mid-thread.
    """

    def initWithShutdownController_(self, shutdown_controller):
        self = objc.super(SwarmAppDelegate, self).init()
        if self is None:
            return None
        self.shutdown_controller = shutdown_controller
        return self

    def applicationShouldTerminate_(self, sender):
        self.shutdown_controller.teardown_ui_and_stop_loop()
        return NSTerminateCancel

    def applicationShouldTerminateAfterLastWindowClosed_(self, sender):
        return False


class SwarmWindowDelegate(NSObject):
    """Stops the event loop cleanly when the user clicks the macOS red close button."""

    def initWithShutdownController_(self, shutdown_controller):
        self = objc.super(SwarmWindowDelegate, self).init()
        if self is None:
            return None
        self.shutdown_controller = shutdown_controller
        return self

    def windowWillClose_(self, notification):
        self.shutdown_controller.teardown_ui_and_stop_loop()


class SignalWatcher(NSObject):
    """Polls for SIGINT/SIGTERM on the main RunLoop so Ctrl+C exits cleanly."""

    def initWithShutdownController_(self, shutdown_controller):
        self = objc.super(SignalWatcher, self).init()
        if self is None:
            return None
        self.shutdown_controller = shutdown_controller
        return self

    def checkSignal_(self, timer):
        if _SIGNAL_RECEIVED.is_set():
            self.shutdown_controller.teardown_ui_and_stop_loop()


class WindowBridgeHandler(NSObject):
    def initWithWindow_shutdownController_(self, window, shutdown_controller):
        self = objc.super(WindowBridgeHandler, self).init()
        if self is None:
            return None
        self.window = window
        self.shutdown_controller = shutdown_controller
        return self

    def userContentController_didReceiveScriptMessage_(self, controller, message):
        try:
            body = message.body()
            data = json.loads(body) if isinstance(body, str) else dict(body)
            action = data.get("type")

            if action == "resize_right":
                # Keep left & top edges anchored; expand/contract strictly to the right
                new_w = float(data.get("width", 920))
                frame = self.window.frame()
                new_frame = NSMakeRect(frame.origin.x, frame.origin.y, new_w, frame.size.height)
                self.window.setFrame_display_animate_(new_frame, True, True)

            elif action == "minimize":
                self.window.miniaturize_(None)

            elif action == "quit":
                self.shutdown_controller.teardown_ui_and_stop_loop()
        except Exception as exc:
            log(f"[SwarmGUI] Window bridge error: {exc}", "warning")


def start_backend_server() -> tuple[uvicorn.Server, threading.Thread]:
    config = uvicorn.Config(
        "swarm_server:app",
        host=HOST,
        port=PORT,
        log_level="warning",
        timeout_graceful_shutdown=3,
    )
    server = uvicorn.Server(config)
    # Main thread owns SIGINT/SIGTERM so graceful shutdown runs in one place
    server.install_signal_handlers = lambda: None
    thread = threading.Thread(target=server.run, name="swarm_uvicorn", daemon=True)
    thread.start()

    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/api/config", timeout=0.5)
            return server, thread
        except Exception:
            time.sleep(0.1)

    return server, thread


def build_main_menu():
    """Creates a standard macOS menu bar with App, Edit, and Window menus so Cmd+V/C/X/A/Z work in WKWebView."""
    main_menu = NSMenu.alloc().init()

    # App menu
    app_menu_item = NSMenuItem.alloc().init()
    main_menu.addItem_(app_menu_item)
    app_menu = NSMenu.alloc().init()
    app_menu.addItemWithTitle_action_keyEquivalent_("Hide Local Agent Swarm", "hide:", "h")
    app_menu.addItem_(NSMenuItem.separatorItem())
    app_menu.addItemWithTitle_action_keyEquivalent_("Quit Local Agent Swarm", "terminate:", "q")
    app_menu_item.setSubmenu_(app_menu)

    # Edit menu (required by macOS AppKit for Cmd+C/V/X/A/Z key equivalents in WKWebView)
    edit_menu_item = NSMenuItem.alloc().init()
    main_menu.addItem_(edit_menu_item)
    edit_menu = NSMenu.alloc().initWithTitle_("Edit")
    edit_menu.addItemWithTitle_action_keyEquivalent_("Undo", "undo:", "z")
    redo_item = edit_menu.addItemWithTitle_action_keyEquivalent_("Redo", "redo:", "z")
    redo_item.setKeyEquivalentModifierMask_(NSEventModifierFlagCommand | NSEventModifierFlagShift)
    edit_menu.addItem_(NSMenuItem.separatorItem())
    edit_menu.addItemWithTitle_action_keyEquivalent_("Cut", "cut:", "x")
    edit_menu.addItemWithTitle_action_keyEquivalent_("Copy", "copy:", "c")
    edit_menu.addItemWithTitle_action_keyEquivalent_("Paste", "paste:", "v")
    edit_menu.addItemWithTitle_action_keyEquivalent_("Select All", "selectAll:", "a")
    edit_menu_item.setSubmenu_(edit_menu)

    # Window menu
    window_menu_item = NSMenuItem.alloc().init()
    main_menu.addItem_(window_menu_item)
    window_menu = NSMenu.alloc().initWithTitle_("Window")
    window_menu.addItemWithTitle_action_keyEquivalent_("Minimize", "performMiniaturize:", "m")
    window_menu.addItemWithTitle_action_keyEquivalent_("Close", "performClose:", "w")
    window_menu_item.setSubmenu_(window_menu)

    return main_menu


def launch_native_window(url: str, shutdown_controller: SwarmShutdownController):
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

    app_delegate = SwarmAppDelegate.alloc().initWithShutdownController_(shutdown_controller)
    app.setDelegate_(app_delegate)
    _KEEP_ALIVE.append(app_delegate)

    main_menu = build_main_menu()
    app.setMainMenu_(main_menu)
    _KEEP_ALIVE.append(main_menu)

    app_icon = build_acorn_app_icon()
    if app_icon is not None:
        app.setApplicationIconImage_(app_icon)
        _KEEP_ALIVE.append(app_icon)

    screen = NSScreen.mainScreen().visibleFrame()
    init_w = 960
    init_h = 720
    init_x = screen.origin.x + (screen.size.width - init_w) / 2
    init_y = screen.origin.y + (screen.size.height - init_h) / 2

    style_mask = (
        NSWindowStyleMaskTitled
        | NSWindowStyleMaskClosable
        | NSWindowStyleMaskMiniaturizable
        | NSWindowStyleMaskResizable
    )
    window = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
        NSMakeRect(init_x, init_y, init_w, init_h),
        style_mask,
        NSBackingStoreBuffered,
        False,
    )
    window.setTitle_("Local Agent Swarm")
    window.setLevel_(NSNormalWindowLevel)
    window.setOpaque_(True)
    window.setBackgroundColor_(
        NSColor.colorWithCalibratedRed_green_blue_alpha_(0.039, 0.039, 0.047, 1.0)
    )
    window.setMinSize_((760, 520))

    window_delegate = SwarmWindowDelegate.alloc().initWithShutdownController_(shutdown_controller)
    window.setDelegate_(window_delegate)

    config = WebKit.WKWebViewConfiguration.alloc().init()
    controller = WebKit.WKUserContentController.alloc().init()
    handler = WindowBridgeHandler.alloc().initWithWindow_shutdownController_(
        window, shutdown_controller
    )
    controller.addScriptMessageHandler_name_(handler, "windowBridge")
    config.setUserContentController_(controller)

    signal_watcher = SignalWatcher.alloc().initWithShutdownController_(shutdown_controller)
    signal_timer = NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(
        0.25, signal_watcher, "checkSignal:", None, True
    )

    content_bounds = window.contentView().bounds()
    webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(content_bounds, config)
    webview.setAutoresizingMask_(18)  # NSViewWidthSizable | NSViewHeightSizable

    shutdown_controller.attach_ui(window, webview, controller, signal_timer=signal_timer)
    _KEEP_ALIVE.extend([window, window_delegate, handler, controller, webview, signal_watcher, signal_timer])

    req = NSURLRequest.requestWithURL_(NSURL.URLWithString_(url))
    webview.loadRequest_(req)

    window.setContentView_(webview)
    window.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)

    try:
        app.run()
    finally:
        shutdown_controller.teardown_ui_and_stop_loop()
        app.setDelegate_(None)


def main():
    parser = argparse.ArgumentParser(description="Launch Local Agent Swarm GUI")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="Connect native window to Vite dev server (http://localhost:5173/?live=1)",
    )
    parser.add_argument(
        "--browser",
        action="store_true",
        help="Open the live UI in your default browser instead of the native window",
    )
    args = parser.parse_args()

    _SIGNAL_RECEIVED.clear()
    signal.signal(signal.SIGINT, _handle_exit_signal)
    signal.signal(signal.SIGTERM, _handle_exit_signal)

    server, server_thread = start_backend_server()
    shutdown_controller = SwarmShutdownController(server=server, server_thread=server_thread)

    target_url = (
        "http://localhost:5173/?live=1"
        if args.dev
        else f"http://{HOST}:{PORT}/?live=1"
    )

    try:
        if args.browser:
            print(f"Swarm server running at {target_url}")
            webbrowser.open(target_url)
            while not _SIGNAL_RECEIVED.is_set():
                time.sleep(0.25)
        else:
            launch_native_window(target_url, shutdown_controller)
    except KeyboardInterrupt:
        pass
    finally:
        shutdown_controller.cleanup_backend()


if __name__ == "__main__":
    main()
