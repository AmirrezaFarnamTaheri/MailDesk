from __future__ import annotations

import re
import subprocess
from pathlib import Path

EXPECTED = {
    "mailmerge_app/browser_profiles.py": "f3ac722387542ce2232334d73698a6431618a9d1",
    "mailmerge_app/main.py": "790312e5abfd8125992519f0cc70bb49532f77fe",
    "docs/USER-GUIDE.md": "e3981265b67ff75327234376e372a424ff31ac62",
}
for path, expected in EXPECTED.items():
    actual = subprocess.check_output(["git", "hash-object", path], text=True).strip()
    if actual != expected:
        raise RuntimeError(f"{path} changed: {actual} != {expected}")


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if text.count(old) != 1:
        raise RuntimeError(f"Expected one target in {path}, found {text.count(old)}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def sub_once(path: str, pattern: str, replacement: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, lambda _m: replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"Expected one regex target in {path}, found {count}")
    p.write_text(updated, encoding="utf-8")


# Browser discovery: restore robust Windows executable lookup and preserve Gmail account order.
replace_once("mailmerge_app/browser_profiles.py", "import copy\n", "import base64\nimport copy\n")
sub_once(
    "mailmerge_app/browser_profiles.py",
    r"def _browser_candidates\(\):.*?\n\n\ndef _safe_profile_dir",
    '''def _windows_app_path(executable_name: str) -> Path | None:
    if platform.system() != "Windows":
        return None
    try:
        import winreg
    except ImportError:
        return None
    key_paths = [
        rf"SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{executable_name}",
        rf"SOFTWARE\\WOW6432Node\\Microsoft\\Windows\\CurrentVersion\\App Paths\\{executable_name}",
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


def _safe_profile_dir''',
)
replace_once(
    "mailmerge_app/browser_profiles.py",
    '''            preferences = _read_json(user_data / profile_dir / "Preferences")
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
            )''',
    '''            preferences = _read_json(user_data / profile_dir / "Preferences")
            primary_email, gmail_accounts, emails = _extract_profile_accounts(info, preferences)
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
                    "profile_id": f"{browser_id}|{profile_dir}",
                }
            )''',
)
sub_once(
    "mailmerge_app/browser_profiles.py",
    r"def _read_json\(path: Path\) -> dict:.*?\n\n\ndef _profile_sort_key",
    '''def _read_json(path: Path) -> dict:
    try:
        decoded = json.loads(path.read_text(encoding="utf-8"))
        return decoded if isinstance(decoded, dict) else {}
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
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
            text = text.split("\\n", 1)[1] if "\\n" in text else text[4:]
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


def _profile_sort_key''',
)

# Generic placeholder -> sheet column mapping.
replace_once("mailmerge_app/main.py", '    trim_values: bool = True\n\n\nclass MessagePayload', '    trim_values: bool = True\n    placeholder_mappings: dict[str, str] = Field(default_factory=dict, max_length=200)\n\n\nclass MessagePayload')
replace_once("mailmerge_app/main.py", '@app.get("/api/browser-profiles")\nasync def browser_profiles() -> list[dict[str, object]]:\n    return await asyncio.to_thread(discover_profiles)', '@app.get("/api/browser-profiles")\nasync def browser_profiles(refresh: bool = Query(default=False)) -> list[dict[str, object]]:\n    return await asyncio.to_thread(discover_profiles, force_refresh=refresh)')
replace_once("mailmerge_app/main.py", '    working = {key: (value.strip() if payload.trim_values and isinstance(value, str) else value) for key, value in row.items()}\n    row_number = int(row.get("_row", "0") or 0)', '    working = {key: (value.strip() if payload.trim_values and isinstance(value, str) else value) for key, value in row.items()}\n    for placeholder, column in payload.placeholder_mappings.items():\n        if placeholder not in {"_row", "_today"} and column:\n            working[placeholder] = working.get(column, "")\n    row_number = int(row.get("_row", "0") or 0)')
replace_once("mailmerge_app/main.py", '    optional = [payload.name_column, payload.cc_column, payload.bcc_column, payload.attachment_column, payload.filter_column, payload.sort_column]\n    if any(column and column not in headers for column in required + optional):', '    optional = [payload.name_column, payload.cc_column, payload.bcc_column, payload.attachment_column, payload.filter_column, payload.sort_column]\n    mapped = list(payload.placeholder_mappings.values())\n    if any(column and column not in headers for column in required + optional + mapped):')

Path("tests/test_browser_discovery.py").write_text('''from __future__ import annotations
import base64
import unittest
from unittest.mock import patch
from mailmerge_app.browser_profiles import _browser_candidates, _extract_profile_accounts, _gmail_accounts_from_preferences

def _field_bytes(field: int, value: bytes) -> bytes:
    return bytes([(field << 3) | 2, len(value)]) + value

def _field_bool(field: int, value: bool) -> bytes:
    return bytes([(field << 3) | 0, 1 if value else 0])

def _account(email: str, gaia_id: str, *, valid: bool = True, signed_out: bool = False) -> bytes:
    payload = b"".join([_field_bytes(3, email.encode()), _field_bool(9, valid), _field_bytes(10, gaia_id.encode()), _field_bool(14, signed_out), _field_bool(15, True)])
    return bytes([10, len(payload)]) + payload

class BrowserDiscoveryTests(unittest.TestCase):
    def test_windows_browser_candidates_are_well_formed(self):
        with patch("mailmerge_app.browser_profiles.platform.system", return_value="Windows"):
            candidates = _browser_candidates()
        self.assertTrue(all(len(item) == 4 for item in candidates))
        brave = next(item for item in candidates if item[0] == "brave")
        self.assertTrue(any("Application" in str(path) for path in brave[2] if path))
        self.assertTrue(any("User Data" in str(path) for path in brave[3] if path))

    def test_cached_gaia_accounts_preserve_gmail_order(self):
        encoded = base64.b64encode(_account("first@example.com", "1") + _account("signedout@example.com", "2", signed_out=True) + _account("second@example.com", "3", valid=False)).decode()
        accounts = _gmail_accounts_from_preferences({"gaia_cookie": {"last_list_accounts_binary_data": encoded}})
        self.assertEqual([a["email"] for a in accounts], ["first@example.com", "second@example.com"])
        self.assertEqual([a["slot"] for a in accounts], [0, 1])
        self.assertFalse(accounts[1]["valid"])

    def test_profile_accounts_keep_secondary_hints(self):
        primary, accounts, emails = _extract_profile_accounts({"user_name": "primary@example.com"}, {"account_info": [{"email": "secondary@example.com"}]})
        self.assertEqual(primary, "primary@example.com")
        self.assertEqual(accounts, [])
        self.assertEqual(emails, ["primary@example.com", "secondary@example.com"])
''', encoding="utf-8")

Path("tests/test_placeholder_mapping.py").write_text('''from __future__ import annotations
import unittest
from fastapi import HTTPException
from mailmerge_app.main import RenderRequest, _render_row, _validate_mapping_columns

class PlaceholderMappingTests(unittest.TestCase):
    def _payload(self, **changes):
        values = dict(import_id="import", sheet="Sheet1", to_column="Email", subject="Hello {{First}}", body="Welcome to {{Company}}.", placeholder_mappings={"First": "Full Name", "Company": "Organisation"})
        values.update(changes)
        return RenderRequest(**values)

    def test_placeholder_can_map_to_differently_named_column(self):
        message = _render_row(self._payload(), {"_row": "2", "Email": "ada@example.com", "Full Name": "Ada", "Organisation": "Analytical Engines"}, {}, {})
        self.assertEqual(message["subject"], "Hello Ada")
        self.assertEqual(message["body"], "Welcome to Analytical Engines.")
        self.assertEqual(message["errors"], [])

    def test_mapping_target_must_exist(self):
        with self.assertRaises(HTTPException):
            _validate_mapping_columns(self._payload(placeholder_mappings={"First": "Missing"}), ["Email", "Full Name"])
''', encoding="utf-8")

replace_once("docs/USER-GUIDE.md", 'Start with the built-in **General message** template or create your own. Use placeholders such as `{{Name|there}}`, optional conditions, snippets, HTML, signatures and attachments as needed.\n', 'Start with the built-in **General message** template or create your own. Use placeholders such as `{{Name|there}}`, optional conditions, snippets, HTML, signatures and attachments as needed. **Placeholder mapping** lets a reusable token such as `{{Name}}` read from any spreadsheet column, even when the source header has a different name. The live sheet stays beside the message preview so you can compare source values with the rendered message row by row.\n')
replace_once("docs/USER-GUIDE.md", 'Open **Senders → Browser senders** and add the browser profile, account index and expected email you want to use.\n', 'Open **Senders → Browser senders** and choose a browser profile. MailDesk reads that profile and, when Chromium has cached the signed-in Google session, lists Gmail accounts in browser order so the account index and email can be filled automatically. Click **Rescan browsers** after signing in or changing accounts; manual account-index/email entry remains available as a fallback.\n')

print("backend browser detection and placeholder mapping applied")
