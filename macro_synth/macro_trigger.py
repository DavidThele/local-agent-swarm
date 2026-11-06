"""Trigger a resident macro service run without loading the service runtime."""

import os
import socket
import sys
from pathlib import Path


SOCKET_PATH = Path(
    os.environ.get(
        "MACRO_SERVICE_SOCKET",
        str(Path(os.environ.get("TMPDIR", "/tmp")) / "agents-macro-synth.sock"),
    )
)


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
        print(f"Macro service unavailable: {exc}", file=sys.stderr)
        raise SystemExit(1)
