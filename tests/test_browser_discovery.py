from __future__ import annotations
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
