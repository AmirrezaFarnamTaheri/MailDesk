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

from .instance import acquire_instance_lock
from .main import APP_VERSION, app

APP_PORT = 8765
APP_URL = f"http://127.0.0.1:{APP_PORT}/"


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

    if "--version" in args:
        print(f"MailDesk {APP_VERSION}")
        return

    if "--build-smoke-test" in args:
        index = args.index("--build-smoke-test")
        if index + 1 >= len(args):
            raise SystemExit("--build-smoke-test requires an output path")
        marker = Path(args[index + 1])
        marker.parent.mkdir(parents=True, exist_ok=True)
        marker.write_text(f"MailDesk {APP_VERSION}", encoding="utf-8")
        return

    lock = acquire_instance_lock()
    if lock is None:
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
