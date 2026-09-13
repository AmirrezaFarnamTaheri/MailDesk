from __future__ import annotations

import asyncio
import base64
import email
import hashlib
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from mailmerge_app import sheet_reader
from mailmerge_app.gmail_client import GoogleOutcomeUncertainError, build_raw_message, send_message
from mailmerge_app.storage import Store
from mailmerge_app.template_engine import batch_fingerprint, is_valid_email, message_fingerprint


class GmailMutationSafetyTests(unittest.TestCase):
    def test_success_without_remote_id_is_uncertain_not_retryable_failure(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.return_value = {}
        http = MagicMock()
        http.post = AsyncMock(return_value=response)

        with self.assertRaises(GoogleOutcomeUncertainError):
            asyncio.run(send_message({"access_token": "token"}, "raw-message", http=http))

    def test_malformed_success_body_is_uncertain(self):
        response = MagicMock()
        response.raise_for_status.return_value = None
        response.json.side_effect = ValueError("not json")
        http = MagicMock()
        http.post = AsyncMock(return_value=response)

        with self.assertRaises(GoogleOutcomeUncertainError):
            asyncio.run(send_message({"access_token": "token"}, "raw-message", http=http))

    def test_cancellation_during_send_is_uncertain(self):
        http = MagicMock()
        http.post = AsyncMock(side_effect=asyncio.CancelledError())

        with self.assertRaises(GoogleOutcomeUncertainError) as raised:
            asyncio.run(send_message({"access_token": "token"}, "raw-message", http=http))
        self.assertIn("outcome is uncertain", str(raised.exception))

    def test_mime_parameters_do_not_downgrade_attachment_type(self):
        raw = build_raw_message(
            "to@example.com",
            "Subject",
            "Body",
            attachments=[("note.txt", b"hello", "text/plain; charset=utf-8")],
        )
        padded = raw + "=" * (-len(raw) % 4)
        parsed = email.message_from_bytes(base64.urlsafe_b64decode(padded.encode("ascii")))
        attachment = next(part for part in parsed.walk() if part.get_filename() == "note.txt")
        self.assertEqual(attachment.get_content_type(), "text/plain")


class SpreadsheetSafetyRegressionTests(unittest.TestCase):
    def test_utf8_bom_does_not_pollute_first_csv_header(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "people.csv"
            path.write_bytes("\ufeffEmail,Name\nada@example.com,Ada\n".encode("utf-8"))
            headers, rows, header_row = sheet_reader.table(path, "CSV", 1)
            self.assertEqual(header_row, 1)
            self.assertEqual(headers, ["Email", "Name"])
            self.assertEqual(rows[0]["Email"], "ada@example.com")
            self.assertEqual(sheet_reader.suggest_mappings(headers, rows).get("to"), "Email")

    def test_xlsx_archive_expansion_is_rejected_before_xml_parsing(self):
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "oversized.xlsx"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("xl/worksheets/sheet1.xml", "x" * 128)
            with patch.object(sheet_reader, "MAX_XLSX_UNCOMPRESSED_BYTES", 64):
                with self.assertRaisesRegex(ValueError, "expands beyond"):
                    sheet_reader.list_sheets(path)


class TemplateSafetyRegressionTests(unittest.TestCase):
    def test_email_validation_rejects_invalid_domain_and_dot_atom_forms(self):
        self.assertFalse(is_valid_email("person@bad_domain.example"))
        self.assertFalse(is_valid_email("first..last@example.com"))
        self.assertFalse(is_valid_email(".first@example.com"))
        self.assertFalse(is_valid_email("last.@example.com"))
        self.assertTrue(is_valid_email("person+tag@example.com"))
        self.assertTrue(is_valid_email("person@bücher.de"))

    def test_message_fingerprint_has_no_delimiter_collision(self):
        left = message_fingerprint(
            "send", "sender@example.com", "to@example.com", "", "", "A|B", "C"
        )
        right = message_fingerprint(
            "send", "sender@example.com", "to@example.com", "", "", "A", "B|C"
        )
        self.assertNotEqual(left, right)

    def test_message_fingerprint_preserves_legacy_hash_when_unambiguous(self):
        fields = [
            "send",
            "sender@example.com",
            "to@example.com",
            "",
            "",
            "Subject",
            "Body",
            "<p>Body</p>",
            "attachment-a,attachment-b",
        ]
        legacy = hashlib.sha256("|".join(fields).encode("utf-8")).hexdigest()
        actual = message_fingerprint(
            "send",
            "sender@example.com",
            "to@example.com",
            "",
            "",
            "Subject",
            "Body",
            "<p>Body</p>",
            ["attachment-b", "attachment-a"],
        )
        self.assertEqual(actual, legacy)

    def test_batch_fingerprint_has_no_delimiter_collision(self):
        left = batch_fingerprint([
            {"row_number": "2", "to": "to@example.com", "subject": "A|B", "body": "C"}
        ])
        right = batch_fingerprint([
            {"row_number": "2", "to": "to@example.com", "subject": "A", "body": "B|C"}
        ])
        self.assertNotEqual(left, right)


class QueuePersistenceRegressionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.old_data_dir = os.environ.get("MAILMERGE_DATA_DIR")
        self.old_skip_backup = os.environ.get("MAILMERGE_SKIP_AUTO_BACKUP")
        os.environ["MAILMERGE_DATA_DIR"] = self.tmp.name
        os.environ["MAILMERGE_SKIP_AUTO_BACKUP"] = "1"
        self.path = Path(self.tmp.name) / "queue.db"

    def tearDown(self) -> None:
        if self.old_data_dir is None:
            os.environ.pop("MAILMERGE_DATA_DIR", None)
        else:
            os.environ["MAILMERGE_DATA_DIR"] = self.old_data_dir
        if self.old_skip_backup is None:
            os.environ.pop("MAILMERGE_SKIP_AUTO_BACKUP", None)
        else:
            os.environ["MAILMERGE_SKIP_AUTO_BACKUP"] = self.old_skip_backup
        self.tmp.cleanup()

    def _campaign(self, store: Store, count: int = 1) -> dict:
        messages = [
            {
                "row_number": str(index + 2),
                "to": f"person{index}@example.com",
                "cc": "",
                "bcc": "",
                "subject": "Subject",
                "body": "Body",
                "body_html": "",
                "attachments": [],
                "fingerprint": f"fp-{index}",
            }
            for index in range(count)
        ]
        return store.create_campaign(
            {
                "name": "Persistence test",
                "mode": "send",
                "account": "sender@example.com",
                "batch_id": "batch-persistence",
                "status": "Paused",
                "throttle_ms": 0,
                "skip_duplicates": True,
            },
            messages,
        )

    def test_success_outbox_restores_history_before_duplicate_checks(self):
        store = Store(self.path)
        campaign = self._campaign(store)
        item = campaign["items"][0]

        # Simulate the exact crash window: the remote Gmail operation completed and
        # the local queue outcome committed, but the following history insert never
        # ran because the process died.
        store.update_item(item["id"], status="Success", remote_id="gmail-123", increment_attempt=True)
        self.assertTrue(store.fingerprint_succeeded(item["fingerprint"]))
        self.assertEqual(store.history(), [])

        restarted = Store(self.path)
        history = restarted.history()
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0]["result"], "Success")
        self.assertEqual(history[0]["remote_id"], "gmail-123")
        self.assertEqual(history[0]["fingerprint"], item["fingerprint"])
        self.assertTrue(restarted.fingerprint_succeeded(item["fingerprint"]))

        # Recovery consumes the outbox in the same transaction as the history
        # insert, so subsequent restarts must not duplicate the audit entry.
        restarted_again = Store(self.path)
        self.assertEqual(len(restarted_again.history()), 1)

    def test_campaign_counters_follow_status_transitions_without_rescan(self):
        store = Store(self.path)
        campaign = self._campaign(store, count=2)
        first, second = campaign["items"]

        store.update_item(first["id"], status="Success", remote_id="one")
        store.update_item(second["id"], status="Failed", error="failed")
        current = store.get_campaign(campaign["id"])
        self.assertEqual((current["success"], current["failed"], current["skipped"]), (1, 1, 0))

        self.assertEqual(store.retry_failed(campaign["id"]), 1)
        current = store.get_campaign(campaign["id"])
        self.assertEqual((current["success"], current["failed"], current["skipped"]), (1, 0, 0))

        store.update_item(second["id"], status="Success", remote_id="two")
        current = store.get_campaign(campaign["id"])
        self.assertEqual((current["success"], current["failed"], current["skipped"]), (2, 0, 0))


if __name__ == "__main__":
    unittest.main()
