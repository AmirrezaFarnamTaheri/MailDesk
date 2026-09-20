from __future__ import annotations

import base64
import copy
import json
import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

MAX_BROWSER_COMPOSE_URL_CHARS = 24_000
_PROFILE_CACHE_TTL_SECONDS = 5.0
_profile_cache: list[dict[str, object]] | None = None
_profile_cache_at = 0.0


def _first_existing(paths: list[Path | None]) -> Path | None:
    for path in paths:
        if path and path.exists():
            return path
    return None


def _windows_app_path(executable_name: str) -> Path | None:
    if platform.system() != "Windows":
        return None
    try:
        import winreg
    except ImportError:
        return None
    key_paths = [
        rf"SOFTWARE\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}",
        rf"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\App Paths\{executable_name}",
    ]
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for key_path in key_paths:
            try:
                with winreg.OpenKey(root, key_path) as key:
                    raw = winreg.QueryValueEx(key, None)[0]
            except OSError:
                continue
            if isinstance(raw, str):
                candidate = Path(os.path.expandvars(raw.strip().strip('"')))
                if candidate.is_file():
                    return candidate
    return None


def _browser_candidates():
    home = Path.home()
    system = platform.system()
    if system == "Windows":
        local = Path(os.getenv("LOCALAPPDATA", home / "AppData" / "Local"))
        program_files = [Path(os.getenv("PROGRAMFILES", "C:/Program Files")), Path(os.getenv("PROGRAMFILES(X86)", "C:/Program Files (x86)"))]
        return [
            ("chrome", "Google Chrome", [_windows_app_path("chrome.exe"), local / "Google/Chrome/Application/chrome.exe", *(p / "Google/Chrome/Application/chrome.exe" for p in program_files)], [local / "Google/Chrome/User Data"]),
            ("edge", "Microsoft Edge", [_windows_app_path("msedge.exe"), *(p / "Microsoft/Edge/Application/msedge.exe" for p in program_files), local / "Microsoft/Edge/Application/msedge.exe"], [local / "Microsoft/Edge/User Data"]),
            ("brave", "Brave", [_windows_app_path("brave.exe"), *(p / "BraveSoftware/Brave-Browser/Application/brave.exe" for p in program_files), local / "BraveSoftware/Brave-Browser/Application/brave.exe"], [local / "BraveSoftware/Brave-Browser/User Data"]),
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


def discover_profiles(*, force_refresh: bool = False) -> list[dict[str, object]]:
    global _profile_cache, _profile_cache_at
    now = time.monotonic()
    if not force_refresh and _profile_cache is not None and now - _profile_cache_at < _PROFILE_CACHE_TTL_SECONDS:
        return copy.deepcopy(_profile_cache)

    output: list[dict[str, object]] = []
    for browser_id, name, exe_candidates, data_candidates in _browser_candidates():
        executable = _first_existing(exe_candidates)
        user_data = _first_existing(data_candidates)
        if not executable or not user_data:
            continue
        local_state = _read_json(user_data / "Local State")
        info_cache = local_state.get("profile", {}).get("info_cache", {}) if isinstance(local_state, dict) else {}
        if not isinstance(info_cache, dict):
            info_cache = {}
        raw_profile_dirs = set(info_cache.keys())
        if (user_data / "Default").exists():
            raw_profile_dirs.add("Default")
        raw_profile_dirs.update(p.name for p in user_data.glob("Profile *") if p.is_dir())
        profile_dirs = {safe for value in raw_profile_dirs if (safe := _safe_profile_dir(user_data, value))}
        for profile_dir in sorted(profile_dirs, key=_profile_sort_key):
            raw_info = info_cache.get(profile_dir, {})
            info = raw_info if isinstance(raw_info, dict) else {}
            preferences_path = user_data / profile_dir / "Preferences"
            preferences = _read_json(preferences_path)
            primary_email, gmail_accounts, emails = _extract_profile_accounts(info, preferences)
            try:
                session_cache_age_seconds = max(0, int(time.time() - preferences_path.stat().st_mtime))
            except OSError:
                session_cache_age_seconds = None
            for account in gmail_accounts:
                account["cache_age_seconds"] = session_cache_age_seconds
            output.append(
                {
                    "browser_id": browser_id,
                    "browser_name": name,
                    "executable": str(executable),
                    "user_data": str(user_data),
                    "profile_dir": profile_dir,
                    "profile_name": info.get("name") or ("Default" if profile_dir == "Default" else profile_dir),
                    "primary_email": primary_email,
                    "gmail_accounts": gmail_accounts,
                    "emails": emails,
                    "session_cache_age_seconds": session_cache_age_seconds,
                    "profile_id": f"{browser_id}|{profile_dir}",
                }
            )
    _profile_cache = copy.deepcopy(output)
    _profile_cache_at = now
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
    url = gmail_base_url(gmail_slot) + "?" + urlencode(values)
    # Browser mode passes this URL through the OS process command line. Windows'
    # CreateProcess limit is roughly 32K characters for the entire command. Keep a
    # conservative margin for the executable/profile arguments and quoting so a
    # large body fails predictably instead of producing an opaque launch failure.
    if len(url) > MAX_BROWSER_COMPOSE_URL_CHARS:
        raise ValueError(
            "Browser compose content is too large for a reliable browser launch. "
            "Use Gmail drafts/send mode or shorten this message."
        )
    return url


def launch_url(profile: dict[str, object], url: str) -> None:
    executable = str(profile["executable"])
    profile_dir = str(profile["profile_dir"])
    user_data = str(profile.get("user_data") or "")
    if not url.startswith("https://mail.google.com/mail/u/"):
        raise ValueError("Browser senders may only open Gmail URLs.")
    if not Path(executable).is_file():
        raise ValueError("The selected browser executable is no longer available. Rescan browsers and select a working profile.")
    if not user_data or not Path(user_data).is_dir():
        raise ValueError("The selected browser user-data folder is no longer available. Rescan browsers and select a working profile.")
    if not _safe_profile_dir(Path(user_data), profile_dir):
        raise ValueError("The selected browser profile is no longer available. Rescan browsers and select a working profile.")
    subprocess.Popen(
        [executable, f"--user-data-dir={user_data}", f"--profile-directory={profile_dir}", url],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        close_fds=platform.system() != "Windows",
    )


def launch_compose(profile: dict[str, object], url: str) -> None:
    launch_url(profile, url)


def _read_json(path: Path) -> dict:
    # Chromium rewrites Preferences atomically and a scan can land between replace
    # operations. A couple of short retries avoid reporting an empty profile just
    # because the browser happened to be persisting state at that instant.
    for attempt in range(3):
        try:
            decoded = json.loads(path.read_text(encoding="utf-8"))
            return decoded if isinstance(decoded, dict) else {}
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            if attempt < 2:
                time.sleep(0.04 * (attempt + 1))
    return {}


def _pref(root: dict, dotted_key: str):
    if dotted_key in root:
        return root[dotted_key]
    current: object = root
    for part in dotted_key.split("."):
        if not isinstance(current, dict) or part not in current:
            return None
        current = current[part]
    return current


def _email(value: object) -> str:
    if not isinstance(value, str):
        return ""
    value = value.strip()
    return value if "@" in value and not any(ch.isspace() for ch in value) else ""


def _extract_profile_accounts(info: dict, preferences: dict) -> tuple[str, list[dict[str, object]], list[str]]:
    primary_candidates = [
        info.get("user_name"),
        _pref(preferences, "google.services.username"),
        _pref(preferences, "google.services.last_signed_in_username"),
        _pref(preferences, "google.services.last_username"),
    ]
    primary_email = next((email for value in primary_candidates if (email := _email(value))), "")
    gmail_accounts = _gmail_accounts_from_preferences(preferences)
    emails: list[str] = []
    seen: set[str] = set()
    def add(value: object) -> None:
        email = _email(value)
        key = email.casefold()
        if email and key not in seen:
            seen.add(key)
            emails.append(email)
    for account in gmail_accounts:
        add(account.get("email"))
    add(primary_email)
    account_info = preferences.get("account_info", []) if isinstance(preferences, dict) else []
    if isinstance(account_info, list):
        for account in account_info:
            if isinstance(account, dict):
                add(account.get("email"))
    return primary_email, gmail_accounts, emails


def _gmail_accounts_from_preferences(preferences: dict) -> list[dict[str, object]]:
    gaia_cookie = preferences.get("gaia_cookie", {}) if isinstance(preferences, dict) else {}
    if not isinstance(gaia_cookie, dict):
        gaia_cookie = {}
    binary = gaia_cookie.get("last_list_accounts_binary_data") or _pref(preferences, "gaia_cookie.last_list_accounts_binary_data")
    accounts = _parse_binary_list_accounts(binary) if isinstance(binary, str) and binary else []
    source = "browser_session"
    if not accounts:
        legacy = gaia_cookie.get("last_list_accounts_data") or _pref(preferences, "gaia_cookie.last_list_accounts_data")
        accounts = _parse_legacy_list_accounts(legacy) if isinstance(legacy, str) and legacy else []
        source = "browser_session_legacy"
    visible: list[dict[str, object]] = []
    for account in accounts:
        if account.get("signed_out"):
            continue
        email = _email(account.get("email"))
        if not email:
            continue
        visible.append({"slot": len(visible), "email": email, "valid": bool(account.get("valid", True)), "verified": bool(account.get("verified", True)), "source": source})
    return visible


def _parse_binary_list_accounts(value: str) -> list[dict[str, object]]:
    try:
        padded = value + "=" * ((4 - len(value) % 4) % 4)
        data = base64.b64decode(padded, validate=False)
        accounts: list[dict[str, object]] = []
        pos = 0
        while pos < len(data):
            tag, pos = _read_varint(data, pos)
            field, wire = tag >> 3, tag & 7
            if field == 1 and wire == 2:
                length, pos = _read_varint(data, pos)
                end = pos + length
                if end > len(data):
                    return []
                parsed = _parse_binary_account(data[pos:end])
                if parsed:
                    accounts.append(parsed)
                pos = end
            else:
                pos = _skip_wire_value(data, pos, wire)
        return accounts
    except (ValueError, UnicodeDecodeError):
        return []


def _parse_binary_account(data: bytes) -> dict[str, object] | None:
    account: dict[str, object] = {"email": "", "gaia_id": "", "valid": True, "signed_out": False, "verified": True}
    pos = 0
    while pos < len(data):
        tag, pos = _read_varint(data, pos)
        field, wire = tag >> 3, tag & 7
        if field in {3, 10} and wire == 2:
            length, pos = _read_varint(data, pos)
            end = pos + length
            if end > len(data):
                raise ValueError("Truncated ListAccounts string field")
            account["email" if field == 3 else "gaia_id"] = data[pos:end].decode("utf-8")
            pos = end
        elif field in {9, 14, 15} and wire == 0:
            raw, pos = _read_varint(data, pos)
            account[{9: "valid", 14: "signed_out", 15: "verified"}[field]] = bool(raw)
        else:
            pos = _skip_wire_value(data, pos, wire)
    return account if _email(account.get("email")) and account.get("gaia_id") else None


def _parse_legacy_list_accounts(value: str) -> list[dict[str, object]]:
    try:
        text = value.strip()
        if text.startswith(")]}'"):
            text = text.split("\n", 1)[1] if "\n" in text else text[4:]
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []
    accounts: list[dict[str, object]] = []
    def visit(node: object) -> None:
        if not isinstance(node, list):
            return
        if len(node) > 10 and isinstance(node[3], str) and "@" in node[3] and isinstance(node[10], str) and node[10]:
            accounts.append({"email": node[3], "gaia_id": node[10], "valid": bool(node[9]) if len(node) > 9 and isinstance(node[9], (bool, int)) else True, "signed_out": bool(node[14]) if len(node) > 14 and isinstance(node[14], (bool, int)) else False, "verified": bool(node[15]) if len(node) > 15 and isinstance(node[15], (bool, int)) else True})
            return
        for child in node:
            visit(child)
    visit(parsed)
    return accounts


def _read_varint(data: bytes, pos: int) -> tuple[int, int]:
    value = 0
    shift = 0
    while pos < len(data) and shift <= 63:
        byte = data[pos]
        pos += 1
        value |= (byte & 0x7F) << shift
        if not byte & 0x80:
            return value, pos
        shift += 7
    raise ValueError("Invalid protobuf varint")


def _skip_wire_value(data: bytes, pos: int, wire: int) -> int:
    if wire == 0:
        _, pos = _read_varint(data, pos)
    elif wire == 1:
        pos += 8
    elif wire == 2:
        length, pos = _read_varint(data, pos)
        pos += length
    elif wire == 5:
        pos += 4
    else:
        raise ValueError("Unsupported protobuf wire type")
    if pos > len(data):
        raise ValueError("Truncated protobuf value")
    return pos


def _profile_sort_key(name: str) -> tuple[int, str]:
    return (0 if name == "Default" else 1, name.lower())
