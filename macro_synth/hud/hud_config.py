import Quartz

from runtime import (
    BASE_CANVAS_HEIGHT,
    BASE_CANVAS_WIDTH,
    HUD_MARGIN_RIGHT,
    HUD_MARGIN_TOP,
    HUD_POS_X,
    HUD_POS_Y,
    HUD_SCALE,
)


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