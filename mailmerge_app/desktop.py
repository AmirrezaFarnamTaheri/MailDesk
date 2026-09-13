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
APP_URL = "http://127.0.0.1:8765/"


def _instance_lock() -> socket.socket | None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        sock.bind(("127.0.0.1", LOCK_PORT))
        sock.listen(1)
        return sock
    except OSError:
        sock.close()
        return None


def _wait_ready(url: str, timeout: float = 12) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            if httpx.get(url + "api/health", timeout=0.5).status_code == 200:
                return
        except Exception:
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

    # Headless frozen-EXE smoke path. Import pywebview (a common PyInstaller hidden
    # import failure point), then write a marker that the Windows workflow can
    # verify without opening a window or local server. pywebview can initialize
    # pythonnet/CLR state whose normal interpreter teardown may keep a frozen GUI
    # process alive on a headless Windows runner. This branch exists only for the
    # build probe, so after the marker file has been closed we terminate the
    # interpreter directly and let the PyInstaller parent clean up its one-file
    # extraction directory.
    if "--build-smoke-test" in args:
        index = args.index("--build-smoke-test")
        if index + 1 >= len(args):
            raise SystemExit("--build-smoke-test requires an output path")

        marker = Path(args[index + 1])
        marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            import webview  # type: ignore  # noqa: F401
        except BaseException as exc:
            marker.write_text(
                f"ERROR: pywebview import failed: {type(exc).__name__}: {exc}",
                encoding="utf-8",
            )
            os._exit(2)

        marker.write_text(f"MailDesk {APP_VERSION}", encoding="utf-8")
        os._exit(0)

    lock = _instance_lock()
    if lock is None:
        webbrowser.open(APP_URL)
        return

    config = uvicorn.Config(app, host="127.0.0.1", port=8765, log_level="warning")
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
        finally:
            lock.close()
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
        lock.close()


if __name__ == "__main__":
    main()
