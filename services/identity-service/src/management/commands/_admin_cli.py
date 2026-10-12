"""What the admin commands share: who ran them, for the audit log."""

from __future__ import annotations

import getpass
import socket


def operator() -> str:
    """`cli:<server account>@<host>`: admin windows are only ever opened from the server."""
    try:
        user = getpass.getuser()
    except (KeyError, OSError):
        user = "unknown"
    return f"cli:{user}@{socket.gethostname()}"[:120]
