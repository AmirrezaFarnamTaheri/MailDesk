from __future__ import annotations

import base64
import ctypes
import json
import os
import platform
import sqlite3
import uuid
from contextlib import contextmanager
from ctypes import wintypes
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from cryptography.fernet import Fernet

from .paths import backups_dir, data_dir


class SecretBox:
    """Encrypt small local secrets. Uses Windows DPAPI on Windows; Fernet elsewhere."""

    class DATA_BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]

    def __init__(self) -> None:
        self._fallback_key_path = data_dir() / "secret.key"

    def _blob(self, payload: bytes):
        buffer = ctypes.create_string_buffer(payload, len(payload))
        blob = self.DATA_BLOB(len(payload), ctypes.cast(buffer, ctypes.POINTER(ctypes.c_byte)))
        return blob, buffer

    def _protect_windows(self, payload: bytes) -> bytes:
        in_blob, _ = self._blob(payload)
        out_blob = self.DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        if not crypt32.CryptProtectData(ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    def _unprotect_windows(self, payload: bytes) -> bytes:
        in_blob, _ = self._blob(payload)
        out_blob = self.DATA_BLOB()
        crypt32 = ctypes.windll.crypt32
        kernel32 = ctypes.windll.kernel32
        kernel32.LocalFree.argtypes = [ctypes.c_void_p]
        kernel32.LocalFree.restype = ctypes.c_void_p
        if not crypt32.CryptUnprotectData(ctypes.byref(in_blob), None, None, None, None, 0x1, ctypes.byref(out_blob)):
            raise ctypes.WinError()
        try:
            return ctypes.string_at(out_blob.pbData, out_blob.cbData)
        finally:
            kernel32.LocalFree(out_blob.pbData)

    def _fernet(self) -> Fernet:
        if not self._fallback_key_path.exists():
            key = Fernet.generate_key()
            try:
                fd = os.open(self._fallback_key_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                pass
            else:
                try:
                    with os.fdopen(fd, "wb") as output:
                        output.write(key)
                        output.flush()
                        os.fsync(output.fileno())
                except Exception:
                    self._fallback_key_path.unlink(missing_ok=True)
                    raise
            try:
                os.chmod(self._fallback_key_path, 0o600)
            except OSError:
                pass
        return Fernet(self._fallback_key_path.read_bytes())

    def encrypt(self, payload: dict[str, Any]) -> str:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        encrypted = self._protect_windows(raw) if platform.system() == "Windows" else self._fernet().encrypt(raw)
        return base64.b64encode(encrypted).decode("ascii")

    def decrypt(self, encoded: str) -> dict[str, Any]:
        encrypted = base64.b64decode(encoded.encode("ascii"), validate=True)
        raw = self._unprotect_windows(encrypted) if platform.system() == "Windows" else self._fernet().decrypt(encrypted)
        decoded = json.loads(raw.decode("utf-8"))
        if not isinstance(decoded, dict):
            raise ValueError("Stored secret payload is invalid.")
        return decoded


class Store:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (data_dir() / "mailmerge.db")
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.secrets = SecretBox()
        self._backup_before_upgrade()
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=5000")
        return connection

    @contextmanager
    def _db(self):
        connection = self._connect()
        try:
            with connection:
                yield connection
        finally:
            connection.close()

    def _backup_before_upgrade(self) -> None:
        if not self.path.exists() or self.path.stat().st_size == 0 or os.getenv("MAILMERGE_SKIP_AUTO_BACKUP") == "1":
            return
        # Copying only the main .db file is unsafe when SQLite is in WAL mode;
        # committed pages may still live in -wal. The SQLite backup API snapshots a
        # consistent database including WAL content before migrations run.
        stamp = datetime.now().strftime("%Y%m%d")
        target = backups_dir() / f"{self.path.stem}-startup-{stamp}.db"
        if not target.exists():
            temporary = target.with_suffix(target.suffix + f".{uuid.uuid4().hex}.tmp")
            try:
                with sqlite3.connect(self.path, timeout=30) as source, sqlite3.connect(temporary) as destination:
                    source.execute("PRAGMA busy_timeout=5000")
                    source.backup(destination)
                os.replace(temporary, target)
            except (OSError, sqlite3.Error):
                temporary.unlink(missing_ok=True)
        backups = sorted(backups_dir().glob(f"{self.path.stem}-startup-*.db"), key=lambda p: p.stat().st_mtime, reverse=True)
        for old in backups[7:]:
            try:
                old.unlink()
            except OSError:
                pass

    def _initialize(self) -> None:
        with self._db() as db:
            db.executescript(
                """
                CREATE TABLE IF NOT EXISTS templates (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    cc_template TEXT NOT NULL DEFAULT '',
                    bcc_template TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS gmail_accounts (
                    email TEXT PRIMARY KEY COLLATE NOCASE,
                    encrypted_token TEXT NOT NULL,
                    encrypted_client TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS operations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_utc TEXT NOT NULL,
                    mode TEXT NOT NULL,
                    account TEXT NOT NULL,
                    row_number TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    subject TEXT NOT NULL,
                    fingerprint TEXT NOT NULL,
                    remote_id TEXT NOT NULL DEFAULT '',
                    result TEXT NOT NULL,
                    error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_operations_fingerprint_success ON operations(fingerprint, result);

                CREATE TABLE IF NOT EXISTS snippets (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    content TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS browser_senders (
                    id TEXT PRIMARY KEY,
                    label TEXT NOT NULL,
                    browser_id TEXT NOT NULL,
                    profile_dir TEXT NOT NULL,
                    gmail_slot INTEGER NOT NULL,
                    expected_email TEXT NOT NULL,
                    verified_at TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS attachments (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    stored_name TEXT NOT NULL,
                    mime_type TEXT NOT NULL DEFAULT '',
                    size INTEGER NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE TABLE IF NOT EXISTS campaigns (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    source_name TEXT NOT NULL DEFAULT '',
                    mode TEXT NOT NULL,
                    account TEXT NOT NULL DEFAULT '',
                    browser_sender_id TEXT NOT NULL DEFAULT '',
                    batch_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    scheduled_at TEXT NOT NULL DEFAULT '',
                    throttle_ms INTEGER NOT NULL DEFAULT 750,
                    skip_duplicates INTEGER NOT NULL DEFAULT 1,
                    total INTEGER NOT NULL DEFAULT 0,
                    success INTEGER NOT NULL DEFAULT 0,
                    failed INTEGER NOT NULL DEFAULT 0,
                    skipped INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    started_at TEXT NOT NULL DEFAULT '',
                    completed_at TEXT NOT NULL DEFAULT '',
                    last_error TEXT NOT NULL DEFAULT ''
                );
                CREATE INDEX IF NOT EXISTS idx_campaigns_due ON campaigns(status, scheduled_at);
                CREATE TABLE IF NOT EXISTS queue_items (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    campaign_id TEXT NOT NULL REFERENCES campaigns(id) ON DELETE CASCADE,
                    ordinal INTEGER NOT NULL,
                    row_number TEXT NOT NULL,
                    recipient TEXT NOT NULL,
                    cc TEXT NOT NULL DEFAULT '',
                    bcc TEXT NOT NULL DEFAULT '',
                    subject TEXT NOT NULL,
                    body TEXT NOT NULL,
                    body_html TEXT NOT NULL DEFAULT '',
                    attachments_json TEXT NOT NULL DEFAULT '[]',
                    fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'Pending',
                    remote_id TEXT NOT NULL DEFAULT '',
                    error TEXT NOT NULL DEFAULT '',
                    attempts INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS idx_queue_campaign_status ON queue_items(campaign_id, status, ordinal);
                CREATE TABLE IF NOT EXISTS settings (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )
            self._ensure_column(db, "templates", "body_html", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "templates", "signature_html", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "templates", "attachment_ids", "TEXT NOT NULL DEFAULT '[]'")
            self._ensure_column(db, "templates", "tags", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "templates", "default_account", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "templates", "default_browser_sender_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(db, "operations", "campaign_id", "TEXT NOT NULL DEFAULT ''")
            db.execute("CREATE INDEX IF NOT EXISTS idx_operations_campaign ON operations(campaign_id, id)")
            self._seed(db)
            # Running means the process died or restarted mid-flight; never silently continue real sends.
            db.execute(
                "UPDATE campaigns SET status='Paused', last_error='Paused after application restart; review and resume explicitly.' WHERE status='Running'"
            )

    def _ensure_column(self, db: sqlite3.Connection, table: str, column: str, definition: str) -> None:
        cols = {row["name"] for row in db.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in cols:
            db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    def _seed(self, db: sqlite3.Connection) -> None:
        count = db.execute("SELECT COUNT(*) FROM templates").fetchone()[0]
        if count:
            return
        now = _utc_now()
        for item in [
            (
                "interview-fa",
                "Interview schedule (Persian)",
                "زمان‌بندی مصاحبه تسهیلات - {{نام دانشجو}}",
                "با سلام\n\n{{نام دانشجو}} گرامی،\n\nبه اطلاع می‌رساند مصاحبه شما در روز {{روز|تاریخ اعلام‌شده}} {{تاریخ}}، ساعت {{ساعت}}، به صورت {{شیوه}} برگزار خواهد شد.\n\nبا آرزوی موفقیت",
            ),
            ("simple-outreach", "Simple outreach", "Hello {{Name|there}}", "Hello {{Name|there}},\n\nWrite your message here.\n\nBest regards,"),
        ]:
            db.execute(
                """INSERT INTO templates(id,name,subject,body,cc_template,bcc_template,body_html,signature_html,attachment_ids,tags,default_account,default_browser_sender_id,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (item[0], item[1], item[2], item[3], "", "", "", "", "[]", "", "", "", now, now),
            )
        db.execute(
            "INSERT OR IGNORE INTO snippets(id,name,content,created_at,updated_at) VALUES(?,?,?,?,?)",
            ("follow-up", "Follow-up line", "Just following up on the message below.", now, now),
        )

    # ---------- templates / snippets ----------
    def list_templates(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM templates ORDER BY name COLLATE NOCASE").fetchall()
        return [self._decode_template(dict(row)) for row in rows]

    def save_template(self, item: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        with self._db() as db:
            existing = db.execute("SELECT created_at FROM templates WHERE id=?", (item["id"],)).fetchone()
            created_at = existing["created_at"] if existing else now
            db.execute(
                """
                INSERT INTO templates(id,name,subject,body,cc_template,bcc_template,body_html,signature_html,attachment_ids,tags,default_account,default_browser_sender_id,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET
                    name=excluded.name, subject=excluded.subject, body=excluded.body,
                    cc_template=excluded.cc_template, bcc_template=excluded.bcc_template,
                    body_html=excluded.body_html, signature_html=excluded.signature_html,
                    attachment_ids=excluded.attachment_ids, tags=excluded.tags,
                    default_account=excluded.default_account, default_browser_sender_id=excluded.default_browser_sender_id,
                    updated_at=excluded.updated_at
                """,
                (
                    item["id"], item["name"], item.get("subject", ""), item.get("body", ""),
                    item.get("cc_template", ""), item.get("bcc_template", ""), item.get("body_html", ""),
                    item.get("signature_html", ""), json.dumps(item.get("attachment_ids", [])), item.get("tags", ""),
                    item.get("default_account", ""), item.get("default_browser_sender_id", ""), created_at, now,
                ),
            )
            row = db.execute("SELECT * FROM templates WHERE id=?", (item["id"],)).fetchone()
        return self._decode_template(dict(row))

    def _decode_template(self, row: dict[str, Any]) -> dict[str, Any]:
        try:
            row["attachment_ids"] = json.loads(row.get("attachment_ids") or "[]")
        except (json.JSONDecodeError, TypeError):
            row["attachment_ids"] = []
        return row

    def delete_template(self, template_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM templates WHERE id=?", (template_id,))

    def list_snippets(self) -> list[dict[str, str]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM snippets ORDER BY name COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]

    def save_snippet(self, item: dict[str, str]) -> dict[str, str]:
        now = _utc_now()
        with self._db() as db:
            existing = db.execute("SELECT created_at FROM snippets WHERE id=?", (item["id"],)).fetchone()
            created_at = existing["created_at"] if existing else now
            db.execute(
                "INSERT INTO snippets(id,name,content,created_at,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name,content=excluded.content,updated_at=excluded.updated_at",
                (item["id"], item["name"], item["content"], created_at, now),
            )
            row = db.execute("SELECT * FROM snippets WHERE id=?", (item["id"],)).fetchone()
            return dict(row)

    def delete_snippet(self, snippet_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM snippets WHERE id=?", (snippet_id,))

    # ---------- Google accounts ----------
    def save_account(self, email: str, token: dict[str, Any], client: dict[str, Any]) -> None:
        with self._db() as db:
            db.execute(
                """INSERT INTO gmail_accounts(email, encrypted_token, encrypted_client, updated_at)
                   VALUES(?,?,?,?) ON CONFLICT(email) DO UPDATE SET encrypted_token=excluded.encrypted_token, encrypted_client=excluded.encrypted_client, updated_at=excluded.updated_at""",
                (email, self.secrets.encrypt(token), self.secrets.encrypt(client), _utc_now()),
            )

    def list_accounts(self) -> list[dict[str, str]]:
        with self._db() as db:
            rows = db.execute("SELECT email, updated_at FROM gmail_accounts ORDER BY email COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]

    def get_account(self, email: str) -> tuple[dict[str, Any], dict[str, Any]] | None:
        with self._db() as db:
            row = db.execute("SELECT encrypted_token, encrypted_client FROM gmail_accounts WHERE email=? COLLATE NOCASE", (email,)).fetchone()
        if not row:
            return None
        return self.secrets.decrypt(row["encrypted_token"]), self.secrets.decrypt(row["encrypted_client"])

    def delete_account(self, email: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM gmail_accounts WHERE email=? COLLATE NOCASE", (email,))

    # ---------- browser sender routes ----------
    def list_browser_senders(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM browser_senders ORDER BY label COLLATE NOCASE").fetchall()
        return [dict(row) for row in rows]

    def get_browser_sender(self, sender_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM browser_senders WHERE id=?", (sender_id,)).fetchone()
        return dict(row) if row else None

    def save_browser_sender(self, item: dict[str, Any]) -> dict[str, Any]:
        now = _utc_now()
        sender_id = item.get("id") or uuid.uuid4().hex
        with self._db() as db:
            existing = db.execute("SELECT created_at, verified_at FROM browser_senders WHERE id=?", (sender_id,)).fetchone()
            created_at = existing["created_at"] if existing else now
            verified_at = item.get("verified_at", existing["verified_at"] if existing else "")
            db.execute(
                """INSERT INTO browser_senders(id,label,browser_id,profile_dir,gmail_slot,expected_email,verified_at,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET label=excluded.label,browser_id=excluded.browser_id,profile_dir=excluded.profile_dir,gmail_slot=excluded.gmail_slot,expected_email=excluded.expected_email,verified_at=excluded.verified_at,updated_at=excluded.updated_at""",
                (sender_id, item["label"], item["browser_id"], item["profile_dir"], int(item["gmail_slot"]), item["expected_email"], verified_at, created_at, now),
            )
            row = db.execute("SELECT * FROM browser_senders WHERE id=?", (sender_id,)).fetchone()
            return dict(row)

    def mark_browser_sender_verified(self, sender_id: str) -> None:
        now = _utc_now()
        with self._db() as db:
            db.execute("UPDATE browser_senders SET verified_at=?,updated_at=? WHERE id=?", (now, now, sender_id))

    def delete_browser_sender(self, sender_id: str) -> None:
        with self._db() as db:
            db.execute("DELETE FROM browser_senders WHERE id=?", (sender_id,))

    # ---------- attachments ----------
    def save_attachment(self, item: dict[str, Any]) -> dict[str, Any]:
        with self._db() as db:
            db.execute(
                "INSERT INTO attachments(id,name,stored_name,mime_type,size,created_at) VALUES(?,?,?,?,?,?)",
                (item["id"], item["name"], item["stored_name"], item.get("mime_type", ""), int(item["size"]), _utc_now()),
            )
            row = db.execute("SELECT * FROM attachments WHERE id=?", (item["id"],)).fetchone()
            return dict(row)

    def list_attachments(self) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM attachments ORDER BY created_at DESC, id DESC").fetchall()
        return [dict(row) for row in rows]

    def get_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM attachments WHERE id=?", (attachment_id,)).fetchone()
        return dict(row) if row else None

    def delete_attachment(self, attachment_id: str) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM attachments WHERE id=?", (attachment_id,)).fetchone()
            if not row:
                return None
            db.execute("DELETE FROM attachments WHERE id=?", (attachment_id,))
            return dict(row)

    # ---------- operations / duplicate protection ----------
    def fingerprint_succeeded(self, fingerprint: str) -> bool:
        with self._db() as db:
            row = db.execute("SELECT 1 FROM operations WHERE fingerprint=? AND result='Success' LIMIT 1", (fingerprint,)).fetchone()
        return bool(row)

    def log_operation(self, item: dict[str, Any]) -> None:
        with self._db() as db:
            db.execute(
                """INSERT INTO operations(timestamp_utc,mode,account,row_number,recipient,subject,fingerprint,remote_id,result,error,campaign_id)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    _utc_now(), item["mode"], item.get("account", ""), item.get("row_number", ""), item.get("recipient", ""),
                    item.get("subject", ""), item.get("fingerprint", ""), item.get("remote_id", ""), item.get("result", "Failed"),
                    item.get("error", ""), item.get("campaign_id", ""),
                ),
            )

    def history(self, limit: int = 200) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM operations ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    # ---------- persistent campaign queue ----------
    def create_campaign(self, campaign: dict[str, Any], messages: list[dict[str, Any]]) -> dict[str, Any]:
        campaign_id = campaign.get("id") or uuid.uuid4().hex
        now = _utc_now()
        with self._db() as db:
            db.execute(
                """INSERT INTO campaigns(id,name,source_name,mode,account,browser_sender_id,batch_id,status,scheduled_at,throttle_ms,skip_duplicates,total,created_at)
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    campaign_id, campaign.get("name") or f"Campaign {now[:10]}", campaign.get("source_name", ""), campaign["mode"],
                    campaign.get("account", ""), campaign.get("browser_sender_id", ""), campaign["batch_id"], campaign.get("status", "Queued"),
                    campaign.get("scheduled_at", ""), int(campaign.get("throttle_ms", 750)), 1 if campaign.get("skip_duplicates", True) else 0,
                    len(messages), now,
                ),
            )
            for ordinal, message in enumerate(messages, start=1):
                db.execute(
                    """INSERT INTO queue_items(campaign_id,ordinal,row_number,recipient,cc,bcc,subject,body,body_html,attachments_json,fingerprint,status,updated_at)
                       VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        campaign_id, ordinal, message.get("row_number", ""), message.get("to", ""), message.get("cc", ""), message.get("bcc", ""),
                        message.get("subject", ""), message.get("body", ""), message.get("body_html", ""), json.dumps(message.get("attachments", [])),
                        message["fingerprint"], "Pending", now,
                    ),
                )
        return self.get_campaign(campaign_id, include_items=True) or {}

    def list_campaigns(self, limit: int = 100) -> list[dict[str, Any]]:
        with self._db() as db:
            rows = db.execute("SELECT * FROM campaigns ORDER BY created_at DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def get_campaign(self, campaign_id: str, include_items: bool = False) -> dict[str, Any] | None:
        with self._db() as db:
            row = db.execute("SELECT * FROM campaigns WHERE id=?", (campaign_id,)).fetchone()
            if not row:
                return None
            result = dict(row)
            if include_items:
                items = db.execute("SELECT * FROM queue_items WHERE campaign_id=? ORDER BY ordinal", (campaign_id,)).fetchall()
                result["items"] = [self._decode_queue_item(dict(item)) for item in items]
        return result

    def _decode_queue_item(self, item: dict[str, Any]) -> dict[str, Any]:
        try:
            item["attachments"] = json.loads(item.pop("attachments_json", "[]") or "[]")
        except (json.JSONDecodeError, TypeError):
            item["attachments"] = []
        return item

    def queue_items(self, campaign_id: str, statuses: Iterable[str] = ("Pending", "Retry")) -> list[dict[str, Any]]:
        values = tuple(statuses)
        if not values:
            return []
        placeholders = ",".join("?" for _ in values)
        with self._db() as db:
            rows = db.execute(
                f"SELECT * FROM queue_items WHERE campaign_id=? AND status IN ({placeholders}) ORDER BY ordinal",
                (campaign_id, *values),
            ).fetchall()
        return [self._decode_queue_item(dict(row)) for row in rows]

    def update_item(self, item_id: int, *, status: str, remote_id: str = "", error: str = "", increment_attempt: bool = False) -> None:
        with self._db() as db:
            db.execute(
                "UPDATE queue_items SET status=?,remote_id=?,error=?,attempts=attempts+?,updated_at=? WHERE id=?",
                (status, remote_id, error, 1 if increment_attempt else 0, _utc_now(), item_id),
            )

    def set_campaign_status(self, campaign_id: str, status: str, *, error: str = "") -> None:
        now = _utc_now()
        with self._db() as db:
            if status == "Running":
                db.execute(
                    "UPDATE campaigns SET status=?,started_at=CASE WHEN started_at='' THEN ? ELSE started_at END,completed_at='',last_error=? WHERE id=?",
                    (status, now, error, campaign_id),
                )
            elif status in {"Completed", "CompletedWithErrors", "Cancelled"}:
                db.execute("UPDATE campaigns SET status=?,completed_at=?,last_error=? WHERE id=?", (status, now, error, campaign_id))
            else:
                db.execute("UPDATE campaigns SET status=?,completed_at='',last_error=? WHERE id=?", (status, error, campaign_id))
        self.refresh_campaign_counts(campaign_id)

    def refresh_campaign_counts(self, campaign_id: str) -> None:
        with self._db() as db:
            counts = {row["status"]: row["n"] for row in db.execute("SELECT status,COUNT(*) n FROM queue_items WHERE campaign_id=? GROUP BY status", (campaign_id,)).fetchall()}
            db.execute(
                "UPDATE campaigns SET success=?,failed=?,skipped=? WHERE id=?",
                (counts.get("Success", 0), counts.get("Failed", 0), counts.get("Skipped", 0), campaign_id),
            )

    def retry_failed(self, campaign_id: str) -> int:
        with self._db() as db:
            cursor = db.execute(
                "UPDATE queue_items SET status='Retry',error='',remote_id='',updated_at=? WHERE campaign_id=? AND status='Failed'",
                (_utc_now(), campaign_id),
            )
            return cursor.rowcount

    def due_campaigns(self) -> list[str]:
        now = _utc_now()
        with self._db() as db:
            rows = db.execute("SELECT id FROM campaigns WHERE status='Scheduled' AND scheduled_at<>'' AND scheduled_at<=?", (now,)).fetchall()
        return [row["id"] for row in rows]

    # ---------- settings / backups ----------
    def get_setting(self, key: str, default: str = "") -> str:
        with self._db() as db:
            row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

    def set_setting(self, key: str, value: str) -> None:
        with self._db() as db:
            db.execute(
                "INSERT INTO settings(key,value,updated_at) VALUES(?,?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
                (key, value, _utc_now()),
            )

    def backup(self) -> Path:
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        target = backups_dir() / f"{self.path.stem}-{stamp}.db"
        temporary = target.with_suffix(target.suffix + f".{uuid.uuid4().hex}.tmp")
        try:
            with self._connect() as source, sqlite3.connect(temporary) as destination:
                source.backup(destination)
            os.replace(temporary, target)
        finally:
            temporary.unlink(missing_ok=True)
        return target


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")
