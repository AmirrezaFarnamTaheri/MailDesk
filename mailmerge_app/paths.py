from __future__ import annotations

import os
import platform
from pathlib import Path

APP_NAME = "MailDesk"


def _secure_directory(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        try:
            os.chmod(path, 0o700)
        except OSError:
            pass
    return path


def data_dir() -> Path:
    override = os.getenv("MAILDESK_DATA_DIR") or os.getenv("MAILMERGE_DATA_DIR")
    if override:
        root = Path(override).expanduser().resolve()
    elif platform.system() == "Windows":
        root = Path(os.getenv("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / APP_NAME
    elif platform.system() == "Darwin":
        root = Path.home() / "Library" / "Application Support" / APP_NAME
    else:
        root = Path(os.getenv("XDG_DATA_HOME", Path.home() / ".local" / "share")) / APP_NAME
    return _secure_directory(root)


def imports_dir() -> Path:
    return _ensure("imports")


def attachments_dir() -> Path:
    return _ensure("attachments")


def backups_dir() -> Path:
    return _ensure("backups")


def logs_dir() -> Path:
    return _ensure("logs")


def _ensure(name: str) -> Path:
    return _secure_directory(data_dir() / name)
