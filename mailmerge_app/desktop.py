from __future__ import annotations

import importlib.util
import os
import socket
import sys
from pathlib import Path
import threading
import time
import webbrowser
from typing import TextIO


_GUI_FALLBACK_STREAMS: list[TextIO] = []


def _ensure_standard_streams() -> None:
    """Provide writable streams for Windows GUI/frozen processes.

    PyInstaller ``--windowed`` executables normally start with ``sys.stdout`` and
    ``sys.stderr`` set to ``None``. Several libraries reasonably assume those
    streams exist; Uvicorn's default formatter, for example, probes
    ``sys.stderr.isatty()`` while configuring logging. Give such libraries a real
    text stream without opening a console window. The handles intentionally live
    for the process lifetime.
    """
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is not None:
            continue
        stream = open(os.devnull, "w", encoding="utf-8", errors="replace", buffering=1)
        _GUI_FALLBACK_STREAMS.append(stream)
        setattr(sys, name, stream)


# Repair GUI-process streams before importing third-party modules. This also makes
# any import-time diagnostics from those modules safe in PyInstaller windowed mode.
_ensure_standard_streams()

import httpx
import uvicorn

# Support both normal package imports (console scripts / PyInstaller launcher) and
# direct source execution via ``python mailmerge_app/desktop.py``. Python puts the
# package directory itself on sys.path for direct script execution, so add the
# repository/package parent before using absolute package imports.
if __package__ in {None, ""}:
    package_parent = str(Path(__file__).resolve().parent.parent)
    if package_parent not in sys.path:
        sys.path.insert(0, package_parent)

from mailmerge_app.instance import acquire_instance_lock
from mailmerge_app.main import APP_VERSION, app

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


def _server_config() -> uvicorn.Config:
    # A desktop GUI does not have a terminal and should never ask Uvicorn to infer
    # ANSI/color capabilities from stdio. ``use_colors=False`` also protects this
    # boundary if another launcher replaces the streams after module import.
    _ensure_standard_streams()
    return uvicorn.Config(
        app,
        host="127.0.0.1",
        port=APP_PORT,
        log_level="warning",
        use_colors=False,
    )


def _frozen_gui_integrity_error() -> str:
    """Return a diagnostic when the frozen Windows GUI payload is incomplete.

    Importing ``webview`` itself initializes the Windows/pythonnet backend and can
    block indefinitely on a headless GitHub runner. The packaging smoke test only
    needs to prove that PyInstaller bundled the importable modules and the native
    WebView2 payload. Real interactive startup still imports webview normally.
    """
    missing_modules = [
        name
        for name in ("webview", "pythonnet", "clr_loader")
        if importlib.util.find_spec(name) is None
    ]
    if missing_modules:
        return "missing frozen module(s): " + ", ".join(missing_modules)

    if not getattr(sys, "frozen", False):
        # Source-mode invocation can still exercise argument parsing/version output,
        # but the native bundle checks below only make sense inside PyInstaller.
        return ""

    bundle_root_raw = getattr(sys, "_MEIPASS", "")
    bundle_root = Path(bundle_root_raw) if bundle_root_raw else Path(sys.executable).parent
    required_native = (
        "Microsoft.Web.WebView2.Core.dll",
        "Microsoft.Web.WebView2.WinForms.dll",
    )
    missing_native = [
        filename
        for filename in required_native
        if not any(bundle_root.rglob(filename))
    ]
    if missing_native:
        return "missing frozen WebView2 asset(s): " + ", ".join(missing_native)

    webview_js = bundle_root / "webview" / "js"
    if not webview_js.is_dir() or not any(webview_js.rglob("*.js")):
        return "missing frozen pywebview JavaScript assets"
    return ""


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

        # Do not import webview in a headless smoke process: on Windows that can
        # initialize pythonnet/.NET and block before CI can observe the marker.
        # Verify the frozen import table/native assets AND configure the same
        # Uvicorn server object used by real startup. The latter catches windowed
        # executables whose stdout/stderr are None before users receive the binary.
        try:
            integrity_error = _frozen_gui_integrity_error()
            _server_config()
        except BaseException as exc:
            marker.write_text(
                f"ERROR: frozen GUI bootstrap probe failed: {type(exc).__name__}: {exc}",
                encoding="utf-8",
            )
            os._exit(2)
        if integrity_error:
            marker.write_text(f"ERROR: {integrity_error}", encoding="utf-8")
            os._exit(2)

        marker.write_text(f"MailDesk {APP_VERSION}", encoding="utf-8")
        os._exit(0)

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

        server = uvicorn.Server(_server_config())
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
