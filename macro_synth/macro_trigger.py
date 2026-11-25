"""Trigger a resident macro service run without loading the service runtime."""

import os
import socket
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv
load_dotenv()

from runtime import SOCKET_PATH


def _notify_service_not_running() -> None:
    if sys.platform != "darwin":
        return
    script = (
        'display notification "Resident HUD service (MacroService) is not started." '
        'with title "Resident HUD Service Not Running"'
    )
    try:
        subprocess.Popen(
            ["osascript", "-e", script],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except Exception:
        pass


def trigger_service() -> str:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(2.0)
        client.connect(str(SOCKET_PATH))
        client.sendall(b"trigger\n")
        return client.recv(64).decode("utf-8").strip()


if __name__ == "__main__":
    try:
        print(trigger_service())
    except OSError as exc:
        _notify_service_not_running()
        print(f"Macro service unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
