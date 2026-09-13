from __future__ import annotations

import socket

LOCK_PORT = 47631


def acquire_instance_lock() -> socket.socket | None:
    """Acquire MailDesk's machine-local process guard.

    The listening socket is intentionally kept open for the lifetime of the
    process. Using a dedicated loopback port works on supported desktop platforms
    without adding platform-specific file-lock dependencies.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", LOCK_PORT))
        sock.listen(1)
        return sock
    except OSError:
        sock.close()
        return None
