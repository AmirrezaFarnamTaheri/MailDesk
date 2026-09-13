from __future__ import annotations

import importlib
import os
import tempfile
import time
import unittest
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

    def test_health_import_mapping_preview_and_render_validation(self):
        self.assertEqual(self.client.get("/api/health").json()["version"], "0.2.0")
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
        status=""
        for _ in range(50):
            status=self.client.get(f"/api/campaigns/{cid}").json()["status"]
            if status in {"Completed","CompletedWithErrors"}: break
            time.sleep(.02)
        campaign=self.client.get(f"/api/campaigns/{cid}").json()
        self.assertEqual(status,"Completed"); self.assertEqual(campaign["success"],2)
        self.assertTrue(all(item["remote_id"]=="DryRunOnly" for item in campaign["items"]))

    def test_send_requires_exact_batch_confirmation_before_account_lookup(self):
        messages=[{"row_number":"2","display_name":"","to":"to@example.com","cc":"","bcc":"","subject":"Subject","body":"Body","body_html":"","attachments":[],"errors":[],"warnings":[]}]
        batch_id=self.client.post('/api/batch-id',json={"messages":messages}).json()["batch_id"]
        response=self.client.post('/api/campaigns',json={"name":"Send","mode":"send","account":"missing@example.com","batch_id":batch_id,"messages":messages,"skip_duplicates":True,"throttle_ms":0,"scheduled_at":"","reviewed":False,"confirm_text":""})
        self.assertEqual(response.status_code,400); self.assertIn(f"SEND 1 {batch_id[:8].upper()}",response.json()["detail"])


    def test_cross_origin_mutation_is_blocked(self):
        response = self.client.post('/api/backup', headers={'Origin':'https://evil.example'})
        self.assertEqual(response.status_code, 403)

    def test_attachment_safety_blocks_executable(self):
        response=self.client.post('/api/attachments',files={"file":("payload.ps1",b"Write-Host hi","text/plain")})
        self.assertEqual(response.status_code,400)


if __name__ == "__main__":
    unittest.main()
