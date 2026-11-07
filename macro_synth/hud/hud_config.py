import Quartz

# ==============================================================================
# HUD CONFIGURATION & UNIVERSAL SCALING
# ==============================================================================
# Universal scalar: scales the entire HUD, fonts, radii, arc, and window frame
HUD_SCALE = 1.0

# Position customization:
# Set HUD_POS_X / HUD_POS_Y to explicit screen coordinates (float/int),
# or leave as None to automatically anchor to top-right using the margins below.
HUD_POS_X = None
HUD_POS_Y = None
HUD_MARGIN_RIGHT = 24.0
HUD_MARGIN_TOP = 24.0

# Base unscaled canvas dimensions (sized to comfortably fit shadows, context
# pills, and the pop-out action wheel without clipping during spring bounces)
BASE_CANVAS_WIDTH = 440
BASE_CANVAS_HEIGHT = 250


def get_window_title_for_pid(pid: int) -> str | None:
    """Fetches the frontmost on-screen window title for a given application PID."""
    try:
        options = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        window_list = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        for win in window_list:
            if win.get("kCGWindowOwnerPID") == pid and win.get("kCGWindowLayer", 0) == 0:
                title = win.get("kCGWindowName", "")
                if title:
                    return str(title)
    except Exception:
        pass
    return None