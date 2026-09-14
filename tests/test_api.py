from __future__ import annotations

import importlib
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from io import BytesIO

from fastapi.testclient import TestClient
from openpyxl import Workbook


class ApiFlowTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
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

    def _workbook_bytes(self) -> bytes:
        wb = Workbook(); ws = wb.active; ws.title = "Contacts"
        ws.append(["Name", "Email", "Status"])
        ws.append(["Ada", "ada@example.com", "Ready"])
        ws.append(["Lin", "not-an-email", "Ready"])
        stream = BytesIO(); wb.save(stream); return stream.getvalue()

    def _valid_workbook_bytes(self) -> bytes:
        wb = Workbook(); ws = wb.active; ws.title = "Contacts"
        ws.append(["Name", "Email"]); ws.append(["Ada", "ada@example.com"]); ws.append(["Lin", "lin@example.com"])
        stream = BytesIO(); wb.save(stream); return stream.getvalue()

    def _message(self, to: str = "to@example.com") -> dict:
        return {
            "row_number": "2", "display_name": "", "to": to, "cc": "", "bcc": "",
            "subject": "Subject", "body": "Body", "body_html": "", "attachments": [],
            "errors": [], "warnings": [],
        }

    def _batch_id(self, messages: list[dict]) -> str:
        response = self.client.post("/api/batch-id", json={"messages": messages})
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["batch_id"]

    def _wait_terminal(self, campaign_id: str) -> dict:
        campaign = {}
        for _ in range(100):
            campaign = self.client.get(f"/api/campaigns/{campaign_id}").json()
            if campaign["status"] in {"Completed", "CompletedWithErrors", "Cancelled"}:
                return campaign
            time.sleep(.02)
        self.fail(f"Campaign did not reach a terminal state: {campaign}")

    def test_health_import_mapping_preview_and_render_validation(self):
        self.assertEqual(self.client.get("/api/health").json()["version"], self.main.APP_VERSION)
        upload = self.client.post("/api/imports", files={"file": ("contacts.xlsx", self._workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
        self.assertEqual(upload.status_code, 200, upload.text); data = upload.json()
        preview = self.client.get(f"/api/imports/{data['import_id']}/preview", params={"sheet":"Contacts"})
        self.assertEqual(preview.status_code, 200, preview.text); p = preview.json()
        self.assertEqual(p["suggestions"]["to"], "Email")
        self.assertEqual(len(p["row_numbers"]), 2)
        rendered = self.client.post("/api/render", json={
            "import_id":data["import_id"],"sheet":"Contacts","to_column":"Email","name_column":"Name",
            "subject":"Hello {{Name|there}}","body":"Hi {{Name}}","body_html":"<p>Hi {{Name}}</p>","signature_html":"",
            "cc_template":"","bcc_template":"","attachment_ids":[],"filter_column":"Status","filter_operator":"equals","filter_value":"Ready","selected_rows":[],"limit":0,"trim_values":True,
        })
        self.assertEqual(rendered.status_code, 200, rendered.text); body=rendered.json()
        self.assertEqual(body["total"],2); self.assertEqual(body["valid"],1); self.assertEqual(body["invalid"],1)
        self.assertTrue(body["batch_id"])

    def test_malformed_xlsx_is_rejected(self):
        response = self.client.post("/api/imports", files={"file": ("broken.xlsx", b"not-a-zip", "application/octet-stream")})
        self.assertEqual(response.status_code, 400)

    def test_dry_run_campaign_completes_in_persistent_queue(self):
        upload = self.client.post("/api/imports", files={"file": ("valid.xlsx", self._valid_workbook_bytes(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}).json()
        rendered = self.client.post("/api/render", json={
            "import_id":upload["import_id"],"sheet":"Contacts","to_column":"Email","name_column":"Name","subject":"Hello {{Name}}","body":"Body {{Name}}","body_html":"","signature_html":"","cc_template":"","bcc_template":"","attachment_ids":[],"selected_rows":[],"limit":0,"trim_values":True,
        }).json()
        messages=[{k:v for k,v in m.items() if k!='source'} for m in rendered["messages"]]
        created=self.client.post("/api/campaigns",json={"name":"Dry test","source_name":"valid.xlsx","mode":"dry_run","batch_id":rendered["batch_id"],"messages":messages,"skip_duplicates":True,"throttle_ms":0,"scheduled_at":"","reviewed":True,"confirm_text":""})
        self.assertEqual(created.status_code,200,created.text); cid=created.json()["id"]
        campaign = self._wait_terminal(cid)
        self.assertEqual(campaign["status"],"Completed"); self.assertEqual(campaign["success"],2)
        self.assertTrue(all(item["remote_id"]=="DryRunOnly" for item in campaign["items"]))
        for _ in range(50):
            if cid not in self.main.queue_tasks:
                break
            time.sleep(.01)
        self.assertNotIn(cid, self.main.queue_tasks)

    def test_send_requires_exact_batch_confirmation_before_account_lookup(self):
        messages=[self._message()]
        batch_id=self._batch_id(messages)
        response=self.client.post('/api/campaigns',json={"name":"Send","mode":"send","account":"missing@example.com","batch_id":batch_id,"messages":messages,"skip_duplicates":True,"throttle_ms":0,"scheduled_at":"","reviewed":False,"confirm_text":""})
        self.assertEqual(response.status_code,400); self.assertIn(f"SEND 1 {batch_id[:8].upper()}",response.json()["detail"])

    def test_campaign_api_rejects_blank_recipient_even_if_client_claims_no_errors(self):
        messages = [self._message("")]
        batch_id = self._batch_id(messages)
        response = self.client.post("/api/campaigns", json={
            "name":"Invalid","mode":"dry_run","batch_id":batch_id,"messages":messages,
            "skip_duplicates":True,"throttle_ms":0,"scheduled_at":"","reviewed":True,"confirm_text":"",
        })
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Recipient is blank", response.json()["detail"])

    def test_subject_line_break_is_rejected_before_queue_execution(self):
        message = self._message("header@example.com")
        message["subject"] = "Hello\nBcc: injected@example.com"
        batch_id = self._batch_id([message])
        response = self.client.post("/api/campaigns", json={
            "name":"Header safety","mode":"dry_run","batch_id":batch_id,"messages":[message],
            "skip_duplicates":False,"throttle_ms":0,"scheduled_at":"","reviewed":True,"confirm_text":"",
        })
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("Subject contains a line break", response.json()["detail"])

    def test_batch_limit_rejects_before_scanning_all_message_fields(self):
        previous = self.client.get("/api/settings").json()
        self.client.put("/api/settings", json={"max_batch_size": 2, "default_throttle_ms": previous["default_throttle_ms"]})
        try:
            messages = [self._message("") for _ in range(3)]
            response = self.client.post("/api/campaigns", json={
                "name":"Too large","mode":"dry_run","batch_id":"0123456789abcdef","messages":messages,
                "skip_duplicates":False,"throttle_ms":0,"scheduled_at":"","reviewed":True,"confirm_text":"",
            })
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn("current safety limit is 2", response.json()["detail"])
            self.assertNotIn("Recipient is blank", response.json()["detail"])
        finally:
            self.client.put("/api/settings", json=previous)

    def test_schedule_near_or_in_past_is_rejected_instead_of_sending_now(self):
        messages = [self._message()]
        batch_id = self._batch_id(messages)
        scheduled_at = (datetime.now(timezone.utc) + timedelta(seconds=2)).isoformat()
        response = self.client.post("/api/campaigns", json={
            "name":"Too soon","mode":"dry_run","batch_id":batch_id,"messages":messages,
            "skip_duplicates":True,"throttle_ms":0,"scheduled_at":scheduled_at,"reviewed":True,"confirm_text":"",
        })
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("at least 5 seconds", response.json()["detail"])

    def test_terminal_campaign_cannot_resume_and_retry_without_failures_is_rejected(self):
        messages = [self._message("terminal@example.com")]
        batch_id = self._batch_id(messages)
        created = self.client.post("/api/campaigns", json={
            "name":"Terminal","mode":"dry_run","batch_id":batch_id,"messages":messages,
            "skip_duplicates":False,"throttle_ms":0,"scheduled_at":"","reviewed":True,"confirm_text":"",
        })
        self.assertEqual(created.status_code, 200, created.text)
        cid = created.json()["id"]
        campaign = self._wait_terminal(cid)
        self.assertEqual(campaign["status"], "Completed")
        resume = self.client.post(f"/api/campaigns/{cid}/resume")
        retry = self.client.post(f"/api/campaigns/{cid}/retry-failed")
        self.assertEqual(resume.status_code, 400, resume.text)
        self.assertEqual(retry.status_code, 400, retry.text)
        self.assertEqual(self.client.get(f"/api/campaigns/{cid}").json()["status"], "Completed")

    def test_history_csv_neutralizes_spreadsheet_formulas(self):
        self.main.store.log_operation({
            "campaign_id":"csv","mode":"dry_run","account":"","row_number":"2",
            "recipient":"=HYPERLINK(\"https://example.invalid\")","subject":"+SUM(1,1)",
            "fingerprint":"csv-safe","remote_id":"","result":"Failed","error":"@cmd",
        })
        response = self.client.get("/api/history.csv")
        self.assertEqual(response.status_code, 200, response.text)
        self.assertIn("'=HYPERLINK", response.text)
        self.assertIn("'+SUM", response.text)
        self.assertIn("'@cmd", response.text)

    def test_cross_origin_mutation_is_blocked(self):
        response = self.client.post('/api/backup', headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code, 403)

    def test_attachment_safety_blocks_executable(self):
        response=self.client.post('/api/attachments',files={"file":("payload.ps1",b"Write-Host hi","text/plain")})
        self.assertEqual(response.status_code,400)

    def test_attachment_filename_is_bounded_before_filesystem_write(self):
        long_name = ("a" * 260) + ".txt"
        response = self.client.post('/api/attachments', files={"file": (long_name, b"hello", "text/plain")})
        self.assertEqual(response.status_code, 400, response.text)
        self.assertIn("filename is invalid or too long", response.json()["detail"])

    def test_oversized_oauth_client_is_rejected_instead_of_truncated(self):
        response = self.client.post(
            "/api/accounts/google/start",
            files={"client_secret": ("client.json", b"x" * (self.main.MAX_OAUTH_CLIENT_BYTES + 1), "application/json")},
            data={"include_sheets": "true"},
        )
        self.assertEqual(response.status_code, 413, response.text)
        self.assertIn("larger than 2 MB", response.json()["detail"])

    def test_attachment_changed_after_upload_is_not_served_or_queued(self):
        uploaded = self.client.post(
            "/api/attachments",
            files={"file": ("note.txt", b"original", "text/plain")},
        )
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        attachment_id = uploaded.json()["id"]
        item = self.main.store.get_attachment(attachment_id)
        self.assertIsNotNone(item)
        path = self.main.attachments_dir() / item["stored_name"]
        path.write_bytes(b"changed-size")

        content = self.client.get(f"/api/attachments/{attachment_id}/content")
        self.assertEqual(content.status_code, 409, content.text)

        message = self._message("attachment@example.com")
        message["attachments"] = [attachment_id]
        batch_id = self._batch_id([message])
        queued = self.client.post("/api/campaigns", json={
            "name":"Changed attachment","mode":"dry_run","batch_id":batch_id,"messages":[message],
            "skip_duplicates":False,"throttle_ms":0,"scheduled_at":"","reviewed":True,"confirm_text":"",
        })
        self.assertEqual(queued.status_code, 400, queued.text)
        self.assertIn("changed attachment", queued.json()["detail"].lower())


if __name__ == "__main__":
    unittest.main()
