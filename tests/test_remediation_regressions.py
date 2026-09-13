from __future__ import annotations

import asyncio
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

from mailmerge_app.gmail_client import GoogleOutcomeUncertainError, send_message
from mailmerge_app.storage import Store


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
