from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
from pathlib import Path
from urllib.parse import urlencode


def _first_existing(paths: list[Path | None]) -> Path | None:
    for path in paths:
        if path and path.exists():
            return path
    return None


def _browser_candidates():
    home = Path.home()
    system = platform.system()
    if system == "Windows":
        local = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
        program_files = [Path(os.getenv("PROGRAMFILES", "C:/Program Files")), Path(os.getenv("PROGRAMFILES(X86)", "C:/Program Files (x86)"))]
        return [
            ("chrome", "Google Chrome", [local / "Google/Chrome/Application/chrome.exe", *(p / "Google/Chrome/Application/chrome.exe" for p in program_files)], [local / "Google/Chrome/User Data"]),
            ("edge", "Microsoft Edge", [*(p / "Microsoft/Edge/Application/msedge.exe" for p in program_files), local / "Microsoft/Edge/Application/msedge.exe"], [local / "Microsoft/Edge/User Data"]),
            ("brave", "Brave", [*(p / "BraveSoftware/Brave-Browser/Application/brave.exe" for p in program_files), local / "BraveSoftware/Brave-Browser/Application/brave.exe"], [local / "BraveSoftware/Brave-Browser/User Data"]),
        ]
    if system == "Darwin":
        support = home / "Library/Application Support"
        return [
            ("chrome", "Google Chrome", [Path("/Applications/Google Chrome.app/Contents/MacOS/Google Chrome")], [support / "Google/Chrome"]),
            ("edge", "Microsoft Edge", [Path("/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge")], [support / "Microsoft Edge"]),
            ("brave", "Brave", [Path("/Applications/Brave Browser.app/Contents/MacOS/Brave Browser")], [support / "BraveSoftware/Brave-Browser"]),
        ]
    config = Path(os.getenv("XDG_CONFIG_HOME", home / ".config"))
    return [
        ("chrome", "Google Chrome", [Path(p) if p else None for p in [shutil.which("google-chrome"), shutil.which("google-chrome-stable")]], [config / "google-chrome"]),
        ("chromium", "Chromium", [Path(p) if p else None for p in [shutil.which("chromium"), shutil.which("chromium-browser")]], [config / "chromium"]),
        ("edge", "Microsoft Edge", [Path(p) if p else None for p in [shutil.which("microsoft-edge"), shutil.which("microsoft-edge-stable")]], [config / "microsoft-edge"]),
        ("brave", "Brave", [Path(p) if p else None for p in [shutil.which("brave-browser"), shutil.which("brave")]], [config / "BraveSoftware/Brave-Browser"]),
    ]


def _safe_profile_dir(user_data: Path, value: object) -> str | None:
    if not isinstance(value, str) or not value or value in {".", ".."}:
        return None
    # Chromium profile directories are direct children of the user-data root.
    # Treat Local State as untrusted input and never follow absolute/traversal
    # entries when reading Preferences or constructing launch arguments.
    candidate = Path(value)
    if candidate.is_absolute() or len(candidate.parts) != 1 or "/" in value or "\\" in value:
        return None
    path = user_data / value
    try:
        if not path.is_dir() or path.resolve().parent != user_data.resolve():
            return None
    except OSError:
        return None
    return value


def discover_profiles() -> list[dict[str, object]]:
    output: list[dict[str, object]] = []
    for browser_id, name, exe_candidates, data_candidates in _browser_candidates():
        executable = _first_existing(exe_candidates)
        user_data = _first_existing(data_candidates)
        if not executable or not user_data:
            continue
        local_state = _read_json(user_data / "Local State")
        info_cache = local_state.get("profile", {}).get("info_cache", {}) if isinstance(local_state, dict) else {}
        raw_profile_dirs = set(info_cache.keys()) if isinstance(info_cache, dict) else set()
        if (user_data / "Default").exists():
            raw_profile_dirs.add("Default")
        raw_profile_dirs.update(p.name for p in user_data.glob("Profile *") if p.is_dir())
        profile_dirs = {safe for value in raw_profile_dirs if (safe := _safe_profile_dir(user_data, value))}
        for profile_dir in sorted(profile_dirs, key=_profile_sort_key):
            info = info_cache.get(profile_dir, {}) if isinstance(info_cache, dict) else {}
            preferences = _read_json(user_data / profile_dir / "Preferences")
            emails = _extract_emails(info, preferences)
            output.append(
                {
                    "browser_id": browser_id,
                    "browser_name": name,
                    "executable": str(executable),
                    "user_data": str(user_data),
                    "profile_dir": profile_dir,
                    "profile_name": info.get("name") or ("Default" if profile_dir == "Default" else profile_dir),
                    "emails": emails,
                    "profile_id": f"{browser_id}|{profile_dir}",
                }
            )
    return output


def gmail_base_url(slot: int) -> str:
    if slot < 0 or slot > 99:
        raise ValueError("Gmail account slot must be between 0 and 99.")
    return f"https://mail.google.com/mail/u/{slot}/"


def inbox_url(slot: int) -> str:
    return gmail_base_url(slot) + "#inbox"


def compose_url(
    to: str,
    subject: str,
    body: str,
    cc: str = "",
    bcc: str = "",
    gmail_slot: int = 0,
) -> str:
    values = {"view": "cm", "fs": "1", "tf": "1", "to": to, "su": subject, "body": body}
    if cc:
        values["cc"] = cc
    if bcc:
        values["bcc"] = bcc
    return gmail_base_url(gmail_slot) + "?" + urlencode(values)


def launch_url(profile: dict[str, object], url: str) -> None:
    executable = str(profile["executable"])
    profile_dir = str(profile["profile_dir"])
    if not url.startswith("https://mail.google.com/mail/u/"):
        raise ValueError("Browser sender routes may only open Gmail URLs.")
    subprocess.Popen(
        [executable, f"--profile-directory={profile_dir}", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=platform.system() != "Windows",
    )


def launch_compose(profile: dict[str, object], url: str) -> None:
    launch_url(profile, url)


def _read_json(path: Path) -> dict:
    try:
        # Profile metadata files should be small. Bound reads so a corrupt or
        # replaced browser file cannot consume arbitrary memory during discovery.
        if path.stat().st_size > 16 * 1024 * 1024:
            return {}
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        return {}


def _extract_emails(info: dict, preferences: dict) -> list[str]:
    # These are useful hints for configuration only. Chromium does not expose a stable
    # mapping from account email -> Gmail /u/N/ slot, so the app requires human verification.
    candidates: list[str] = []
    for value in (info.get("user_name"), info.get("gaia_name")):
        if isinstance(value, str) and "@" in value:
            candidates.append(value)
    account_info = preferences.get("account_info", []) if isinstance(preferences, dict) else []
    if isinstance(account_info, list):
        for account in account_info:
            if isinstance(account, dict):
                email = account.get("email")
                if isinstance(email, str) and "@" in email:
                    candidates.append(email)
    return sorted(set(candidates), key=str.lower)


def _profile_sort_key(name: str) -> tuple[int, str]:
    return (0 if name == "Default" else 1, name.lower())
