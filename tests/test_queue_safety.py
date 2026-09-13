from __future__ import annotations

import asyncio
import importlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient

from mailmerge_app.gmail_client import GoogleOutcomeUncertainError
from mailmerge_app.storage import Store


class StoreSafetyTests(unittest.TestCase):
    def test_restart_pauses_orphaned_queued_campaigns_in_all_launch_modes(self):
        with tempfile.TemporaryDirectory() as td:
            old_data = os.environ.get("MAILMERGE_DATA_DIR")
            old_skip = os.environ.get("MAILMERGE_SKIP_AUTO_BACKUP")
            os.environ["MAILMERGE_DATA_DIR"] = td
            os.environ["MAILMERGE_SKIP_AUTO_BACKUP"] = "1"
            try:
                path = Path(td) / "queue.db"
                store = Store(path)
                campaign = store.create_campaign(
                    {"name": "Queued", "mode": "dry_run", "batch_id": "abc123456789", "status": "Queued"},
                    [{"row_number": "2", "to": "a@example.com", "subject": "S", "body": "B", "fingerprint": "fp", "attachments": []}],
                )
                reopened = Store(path)
                recovered = reopened.get_campaign(campaign["id"])
                self.assertEqual(recovered["status"], "Paused")
                self.assertIn("application restart", recovered["last_error"])
            finally:
                if old_data is None:
                    os.environ.pop("MAILMERGE_DATA_DIR", None)
                else:
                    os.environ["MAILMERGE_DATA_DIR"] = old_data
                if old_skip is None:
                    os.environ.pop("MAILMERGE_SKIP_AUTO_BACKUP", None)
                else:
                    os.environ["MAILMERGE_SKIP_AUTO_BACKUP"] = old_skip

    def test_active_campaign_resources_cannot_be_considered_free(self):
        with tempfile.TemporaryDirectory() as td:
            old_data = os.environ.get("MAILMERGE_DATA_DIR")
            old_skip = os.environ.get("MAILMERGE_SKIP_AUTO_BACKUP")
            os.environ["MAILMERGE_DATA_DIR"] = td
            os.environ["MAILMERGE_SKIP_AUTO_BACKUP"] = "1"
            try:
                store = Store(Path(td) / "refs.db")
                store.save_account("work@example.com", {"access_token": "a"}, {"client_id": "i"})
                store.save_browser_sender({
                    "id": "route", "label": "Work", "browser_id": "chrome", "profile_dir": "Default",
                    "gmail_slot": 0, "expected_email": "work@example.com",
                })
                store.save_attachment({"id": "att", "name": "a.txt", "stored_name": "att.txt", "mime_type": "text/plain", "size": 1})
                store.save_template({
                    "id": "t", "name": "T", "subject": "S", "body": "B", "attachment_ids": ["att"],
                    "body_html": "", "signature_html": "", "cc_template": "", "bcc_template": "", "tags": "",
                    "default_account": "", "default_browser_sender_id": "",
                })
                store.create_campaign(
                    {"name": "Send", "mode": "send", "account": "work@example.com", "batch_id": "send12345678", "status": "Paused"},
                    [{"row_number": "2", "to": "a@example.com", "subject": "S", "body": "B", "fingerprint": "send-fp", "attachments": []}],
                )
                store.create_campaign(
                    {"name": "Browser", "mode": "browser", "browser_sender_id": "route", "batch_id": "browser123456", "status": "Scheduled"},
                    [{"row_number": "2", "to": "a@example.com", "subject": "S", "body": "B", "fingerprint": "browser-fp", "attachments": []}],
                )
                self.assertTrue(store.account_in_use("WORK@example.com"))
                self.assertTrue(store.browser_sender_in_use("route"))
                self.assertTrue(store.attachment_in_use("att"))
            finally:
                if old_data is None:
                    os.environ.pop("MAILMERGE_DATA_DIR", None)
                else:
                    os.environ["MAILMERGE_DATA_DIR"] = old_data
                if old_skip is None:
                    os.environ.pop("MAILMERGE_SKIP_AUTO_BACKUP", None)
                else:
                    os.environ["MAILMERGE_SKIP_AUTO_BACKUP"] = old_skip

    def test_existing_database_refuses_upgrade_when_backup_cannot_be_created(self):
        with tempfile.TemporaryDirectory() as td:
            old_data = os.environ.get("MAILMERGE_DATA_DIR")
            old_skip = os.environ.get("MAILMERGE_SKIP_AUTO_BACKUP")
            os.environ["MAILMERGE_DATA_DIR"] = td
            os.environ["MAILMERGE_SKIP_AUTO_BACKUP"] = "1"
            path = Path(td) / "backup.db"
            try:
                Store(path)
                os.environ.pop("MAILMERGE_SKIP_AUTO_BACKUP", None)
                with patch("mailmerge_app.storage.os.replace", side_effect=OSError("disk full")):
                    with self.assertRaisesRegex(RuntimeError, "startup database backup"):
                        Store(path)
            finally:
                if old_data is None:
                    os.environ.pop("MAILMERGE_DATA_DIR", None)
                else:
                    os.environ["MAILMERGE_DATA_DIR"] = old_data
                if old_skip is None:
                    os.environ.pop("MAILMERGE_SKIP_AUTO_BACKUP", None)
                else:
                    os.environ["MAILMERGE_SKIP_AUTO_BACKUP"] = old_skip


class ApiQueueSafetyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.old_data = os.environ.get("MAILMERGE_DATA_DIR")
        cls.old_no_browser = os.environ.get("MAILMERGE_NO_BROWSER")
        cls.old_skip = os.environ.get("MAILMERGE_SKIP_AUTO_BACKUP")
        os.environ["MAILMERGE_DATA_DIR"] = cls.tmp.name
        os.environ["MAILMERGE_NO_BROWSER"] = "1"
        os.environ["MAILMERGE_SKIP_AUTO_BACKUP"] = "1"
        import mailmerge_app.main as main
        cls.main = importlib.reload(main)
        cls.client = TestClient(cls.main.app)
        cls.client.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client.__exit__(None, None, None)
        cls.tmp.cleanup()
        for key, previous in (
            ("MAILMERGE_DATA_DIR", cls.old_data),
            ("MAILMERGE_NO_BROWSER", cls.old_no_browser),
            ("MAILMERGE_SKIP_AUTO_BACKUP", cls.old_skip),
        ):
            if previous is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = previous

    def _uncertain_campaign(self, suffix: str = "one") -> tuple[str, int]:
        fingerprint = f"uncertain-{suffix}"
        campaign = self.main.store.create_campaign(
            {"name": "Uncertain", "mode": "send", "account": "sender@example.com", "batch_id": f"uncertain-{suffix}-123456", "status": "Paused"},
            [{"row_number": "2", "to": "to@example.com", "subject": "S", "body": "B", "fingerprint": fingerprint, "attachments": []}],
        )
        item = campaign["items"][0]
        self.main.store.update_item(item["id"], status="NeedsReview", error="timeout", increment_attempt=True)
        self.main.store.refresh_campaign_counts(campaign["id"])
        return campaign["id"], item["id"]

    def test_uncertain_item_blocks_resume_until_resolved_sent(self):
        campaign_id, item_id = self._uncertain_campaign("sent")
        blocked = self.client.post(f"/api/campaigns/{campaign_id}/resume")
        self.assertEqual(blocked.status_code, 409, blocked.text)

        resolved = self.client.post(f"/api/campaigns/{campaign_id}/items/{item_id}/resolve-sent")
        self.assertEqual(resolved.status_code, 200, resolved.text)
        body = resolved.json()
        item = next(i for i in body["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], "Success")
        self.assertEqual(item["remote_id"], "ConfirmedByUser")
        self.assertEqual(body["status"], "Completed")
        self.assertTrue(body["completed_at"])
        self.assertTrue(self.main.store.fingerprint_succeeded("uncertain-sent"))

    def test_uncertain_item_can_be_resolved_not_sent_as_completed_with_errors(self):
        campaign_id, item_id = self._uncertain_campaign("not-sent")
        resolved = self.client.post(f"/api/campaigns/{campaign_id}/items/{item_id}/resolve-not-sent")
        self.assertEqual(resolved.status_code, 200, resolved.text)
        body = resolved.json()
        item = next(i for i in body["items"] if i["id"] == item_id)
        self.assertEqual(item["status"], "Failed")
        self.assertIn("did not complete", item["error"])
        self.assertEqual(body["status"], "CompletedWithErrors")
        self.assertTrue(body["completed_at"])

    def test_campaign_worker_wrapper_serializes_campaigns(self):
        async def run_test():
            active = 0
            maximum = 0

            async def fake(_campaign_id: str):
                nonlocal active, maximum
                active += 1
                maximum = max(maximum, active)
                await asyncio.sleep(0.02)
                active -= 1

            self.main.campaign_run_lock = asyncio.Lock()
            with patch.object(self.main, "_run_campaign_locked", side_effect=fake):
                await asyncio.gather(self.main._run_campaign("a"), self.main._run_campaign("b"))
            return maximum

        self.assertEqual(asyncio.run(run_test()), 1)

    def test_worker_does_not_start_campaign_paused_while_waiting(self):
        campaign = self.main.store.create_campaign(
            {"name": "Paused", "mode": "dry_run", "batch_id": "paused123456789", "status": "Paused"},
            [{"row_number": "2", "to": "p@example.com", "subject": "S", "body": "B", "fingerprint": "paused-fp", "attachments": []}],
        )
        asyncio.run(self.main._run_campaign_locked(campaign["id"]))
        current = self.main.store.get_campaign(campaign["id"], include_items=True)
        self.assertEqual(current["status"], "Paused")
        self.assertEqual(current["items"][0]["status"], "Pending")

    def test_uncertain_gmail_interruption_pauses_without_replayable_pending_item(self):
        campaign = self.main.store.create_campaign(
            {
                "name": "Interrupted send",
                "mode": "send",
                "account": "sender@example.com",
                "batch_id": "interrupt123456",
                "status": "Queued",
                "throttle_ms": 0,
            },
            [{"row_number": "2", "to": "to@example.com", "subject": "S", "body": "B", "fingerprint": "interrupted-fp", "attachments": []}],
        )
        token = {"access_token": "token", "expires_at": "2999-01-01T00:00:00+00:00", "scope": "https://www.googleapis.com/auth/gmail.compose"}

        async def run_test():
            with patch.object(
                self.main,
                "_verified_google_account",
                AsyncMock(return_value=(token, "sender@example.com")),
            ), patch.object(
                self.main,
                "send_message",
                AsyncMock(side_effect=GoogleOutcomeUncertainError("interrupted in flight")),
            ):
                await self.main._run_campaign_locked(campaign["id"])

        asyncio.run(run_test())
        current = self.main.store.get_campaign(campaign["id"], include_items=True)
        self.assertEqual(current["status"], "Paused")
        self.assertEqual(current["items"][0]["status"], "NeedsReview")
        self.assertEqual(current["items"][0]["attempts"], 1)
        self.assertIn("uncertain", current["last_error"].lower())
        self.assertFalse(self.main.store.fingerprint_succeeded("interrupted-fp"))
        self.assertEqual(self.main.store.history(1)[0]["result"], "Uncertain")

    def test_gmail_campaign_reuses_one_http_pool_for_multiple_messages(self):
        campaign = self.main.store.create_campaign(
            {
                "name": "Pooled send",
                "mode": "send",
                "account": "sender@example.com",
                "batch_id": "pooled-send-1234",
                "status": "Queued",
                "throttle_ms": 0,
                "skip_duplicates": False,
            },
            [
                {"row_number": "2", "to": "one@example.com", "subject": "S1", "body": "B1", "fingerprint": "pool-fp-1", "attachments": []},
                {"row_number": "3", "to": "two@example.com", "subject": "S2", "body": "B2", "fingerprint": "pool-fp-2", "attachments": []},
            ],
        )
        token = {"access_token": "token", "expires_at": "2999-01-01T00:00:00+00:00", "scope": "https://www.googleapis.com/auth/gmail.compose"}
        send = AsyncMock(side_effect=["gmail-1", "gmail-2"])

        async def run_test():
            with patch.object(
                self.main,
                "_verified_google_account",
                AsyncMock(return_value=(token, "sender@example.com")),
            ), patch.object(self.main, "send_message", send):
                await self.main._run_campaign_locked(campaign["id"])

        asyncio.run(run_test())
        current = self.main.store.get_campaign(campaign["id"], include_items=True)
        self.assertEqual(current["status"], "Completed")
        self.assertEqual([item["remote_id"] for item in current["items"]], ["gmail-1", "gmail-2"])
        self.assertEqual(send.await_count, 2)
        first_http = send.await_args_list[0].kwargs.get("http")
        second_http = send.await_args_list[1].kwargs.get("http")
        self.assertIsNotNone(first_http)
        self.assertIs(first_http, second_http)
        self.assertTrue(first_http.is_closed)

    def test_compact_detail_omits_message_bodies_and_includes_review_rows(self):
        campaign = self.main.store.create_campaign(
            {"name": "Compact detail", "mode": "dry_run", "batch_id": "compact-detail-123", "status": "Paused"},
            [
                {"row_number": "2", "to": "one@example.com", "subject": "S1", "body": "A" * 10000, "body_html": "<p>A</p>", "fingerprint": "compact-1", "attachments": []},
                {"row_number": "3", "to": "two@example.com", "subject": "S2", "body": "B" * 10000, "body_html": "<p>B</p>", "fingerprint": "compact-2", "attachments": []},
                {"row_number": "4", "to": "three@example.com", "subject": "S3", "body": "C" * 10000, "body_html": "<p>C</p>", "fingerprint": "compact-3", "attachments": []},
            ],
        )
        third = campaign["items"][2]
        self.main.store.update_item(third["id"], status="NeedsReview", error="verify me")

        response = self.client.get(f"/api/campaigns/{campaign['id']}/detail", params={"limit": 1, "needs_review_limit": 2})
        self.assertEqual(response.status_code, 200, response.text)
        detail = response.json()
        self.assertEqual(detail["total"], 3)
        self.assertEqual(detail["needs_review_total"], 1)
        self.assertEqual(len(detail["items"]), 2)
        self.assertEqual({item["id"] for item in detail["items"]}, {campaign["items"][0]["id"], third["id"]})
        for item in detail["items"]:
            self.assertNotIn("body", item)
            self.assertNotIn("body_html", item)
            self.assertNotIn("attachments", item)

    def test_duplicate_preload_preserves_same_campaign_skip_semantics(self):
        fingerprint = "bulk-duplicate-fingerprint"
        campaign = self.main.store.create_campaign(
            {
                "name": "Bulk duplicate",
                "mode": "dry_run",
                "batch_id": "bulk-duplicate-123",
                "status": "Queued",
                "throttle_ms": 0,
                "skip_duplicates": True,
            },
            [
                {"row_number": "2", "to": "same@example.com", "subject": "S", "body": "B", "fingerprint": fingerprint, "attachments": []},
                {"row_number": "3", "to": "same@example.com", "subject": "S", "body": "B", "fingerprint": fingerprint, "attachments": []},
            ],
        )
        with patch.object(self.main.store, "fingerprint_succeeded", side_effect=AssertionError("per-item lookup should not be used")):
            asyncio.run(self.main._run_campaign_locked(campaign["id"]))
        current = self.main.store.get_campaign(campaign["id"], include_items=True)
        self.assertEqual(current["status"], "Completed")
        self.assertEqual([item["status"] for item in current["items"]], ["Success", "Skipped"])
        self.assertEqual((current["success"], current["skipped"]), (1, 1))


if __name__ == "__main__":
    unittest.main()
