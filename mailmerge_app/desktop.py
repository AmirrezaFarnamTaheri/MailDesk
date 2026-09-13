from __future__ import annotations

import os
import socket
import sys
from pathlib import Path
import threading
import time
import webbrowser

import httpx
import uvicorn

from .main import APP_VERSION, app

LOCK_PORT = 47631
APP_PORT = 8765
APP_URL = f"http://127.0.0.1:{APP_PORT}/"


def _instance_lock() -> socket.socket | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", LOCK_PORT))
        sock.listen(1)
        return sock
    except OSError:
        sock.close()
        return None


def _port_in_use(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.25)
        return sock.connect_ex(("127.0.0.1", port)) == 0


def _wait_ready(url: str, timeout: float = 12) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            response = httpx.get(url + "api/health", timeout=0.5)
            data = response.json() if response.status_code == 200 else {}
            if data.get("status") == "ok" and data.get("version") == APP_VERSION:
                return
        except Exception:
            pass
        time.sleep(0.15)
    raise RuntimeError("MailDesk local server did not start.")


def main() -> None:
    args = sys.argv[1:]

    # Keep a simple version flag for console-capable launches. The production EXE
    # uses the Windows GUI subsystem, so CI uses --build-smoke-test below instead
    # of depending on stdout from a windowed executable.
    if "--version" in args:
        print(f"MailDesk {APP_VERSION}")
        return

    # Frozen-EXE startup probe. Do not initialize pywebview/pythonnet here: the
    # Windows CI runner is headless, and loading the CLR-backed GUI stack can block
    # indefinitely even though the packaged executable itself is healthy. The
    # PyInstaller build still analyzes and bundles pywebview through its hook and
    # explicit hidden imports; this probe verifies that the final one-file EXE can
    # unpack, import MailDesk, dispatch arguments and perform filesystem I/O.
    if "--build-smoke-test" in args:
        index = args.index("--build-smoke-test")
        if index + 1 >= len(args):
            raise SystemExit("--build-smoke-test requires an output path")
        marker = Path(args[index + 1])
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"MailDesk {APP_VERSION}", encoding="utf-8")
        return

    lock = _instance_lock()
    if lock is None:
        # A second instance may arrive while the first is still starting. Open the
        # page only after verifying it really is MailDesk, not an unrelated local
        # service that happens to use the same port.
        try:
            _wait_ready(APP_URL, timeout=8)
        except RuntimeError:
            return
        webbrowser.open(APP_URL)
        return

    try:
        if _port_in_use(APP_PORT):
            raise RuntimeError(f"Port {APP_PORT} is already in use by another local application.")

        config = uvicorn.Config(app, host="127.0.0.1", port=APP_PORT, log_level="warning")
        server = uvicorn.Server(config)
        thread = threading.Thread(target=server.run, daemon=True)
        thread.start()
        _wait_ready(APP_URL)

        try:
            import webview  # type: ignore
        except ImportError:
            webbrowser.open(APP_URL)
            try:
                thread.join()
            except KeyboardInterrupt:
                server.should_exit = True
            return

        try:
            webview.create_window(
                f"MailDesk {APP_VERSION}",
                APP_URL,
                width=1440,
                height=920,
                min_size=(1060, 700),
                confirm_close=False,
            )
            webview.start(debug=(os.getenv("MAILDESK_DEBUG") == "1" or os.getenv("MAILMERGE_DEBUG") == "1"))
        finally:
            server.should_exit = True
            thread.join(timeout=5)
    finally:
        lock.close()


if __name__ == "__main__":
    main()
