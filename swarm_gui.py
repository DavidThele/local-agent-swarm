import argparse
import json
from pathlib import Path
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
    NSEventModifierFlagCommand,
    NSEventModifierFlagShift,
    NSGraphicsContext,
    NSImage,
    NSImageInterpolationNone,
    NSMakeRect,
    NSMenu,
    NSMenuItem,
    NSNormalWindowLevel,
    NSScreen,
    NSWindow,
    NSWindowStyleMaskClosable,
    NSWindowStyleMaskMiniaturizable,
    NSWindowStyleMaskResizable,
    NSWindowStyleMaskTitled,
)
from Foundation import NSMakeSize, NSObject, NSURL, NSURLRequest, NSZeroRect
from PyObjCTools import AppHelper

from infrastructure.logging import log

HOST = "127.0.0.1"
PORT = 8765
REPO_ROOT = Path(__file__).resolve().parent

# Prevent Python GC from collecting Obj-C delegates and message handlers
_KEEP_ALIVE: list[object] = []


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


class SwarmWindowDelegate(NSObject):
    """Terminates the application cleanly when the user clicks the macOS red close button."""

    def windowWillClose_(self, notification):
        NSApplication.sharedApplication().terminate_(None)


class WindowBridgeHandler(NSObject):
    def initWithWindow_(self, window):
        self = objc.super(WindowBridgeHandler, self).init()
        if self is None:
            return None
        self.window = window
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
                NSApplication.sharedApplication().terminate_(None)
        except Exception as exc:
            log(f"[SwarmGUI] Window bridge error: {exc}", "warning")


def start_backend_server():
    config = uvicorn.Config(
        "swarm_server:app",
        host=HOST,
        port=PORT,
        log_level="warning",
    )
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, name="swarm_uvicorn", daemon=True)
    thread.start()

    for _ in range(40):
        try:
            urllib.request.urlopen(f"http://{HOST}:{PORT}/api/config", timeout=0.5)
            return
        except Exception:
            time.sleep(0.1)


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


def launch_native_window(url: str):
    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyRegular)

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

    delegate = SwarmWindowDelegate.alloc().init()
    window.setDelegate_(delegate)

    config = WebKit.WKWebViewConfiguration.alloc().init()
    controller = WebKit.WKUserContentController.alloc().init()
    handler = WindowBridgeHandler.alloc().initWithWindow_(window)
    controller.addScriptMessageHandler_name_(handler, "windowBridge")
    config.setUserContentController_(controller)

    _KEEP_ALIVE.extend([window, delegate, handler, controller])

    content_bounds = window.contentView().bounds()
    webview = WebKit.WKWebView.alloc().initWithFrame_configuration_(content_bounds, config)
    webview.setAutoresizingMask_(18)  # NSViewWidthSizable | NSViewHeightSizable

    req = NSURLRequest.requestWithURL_(NSURL.URLWithString_(url))
    webview.loadRequest_(req)

    window.setContentView_(webview)
    window.makeKeyAndOrderFront_(None)
    app.activateIgnoringOtherApps_(True)

    AppHelper.runEventLoop()


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

    start_backend_server()
    target_url = (
        "http://localhost:5173/?live=1"
        if args.dev
        else f"http://{HOST}:{PORT}/?live=1"
    )

    if args.browser:
        print(f"Swarm server running at {target_url}")
        webbrowser.open(target_url)
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
    else:
        launch_native_window(target_url)


if __name__ == "__main__":
    main()