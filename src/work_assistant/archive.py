from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator

from work_assistant.models import Message


class LocalArchive:
    def __init__(self, path: str | Path):
        self.path = Path(path)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path)
        connection.row_factory = sqlite3.Row
        try:
            self._migrate(connection)
            yield connection
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _migrate(connection: sqlite3.Connection) -> None:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                account TEXT NOT NULL,
                provider_id TEXT NOT NULL,
                thread_id TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                folder TEXT NOT NULL,
                sender TEXT NOT NULL,
                subject TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                payload_sha256 TEXT NOT NULL,
                archived_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account, provider_id)
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS draft_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                account TEXT NOT NULL,
                to_json TEXT NOT NULL,
                subject TEXT NOT NULL,
                body TEXT NOT NULL,
                in_reply_to TEXT,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                status TEXT NOT NULL DEFAULT 'local_candidate'
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS local_artifacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                kind TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS attachment_texts (
                account TEXT NOT NULL,
                message_id TEXT NOT NULL,
                attachment_id TEXT NOT NULL,
                source_sha256 TEXT NOT NULL,
                extractor TEXT,
                status TEXT NOT NULL,
                text TEXT NOT NULL DEFAULT '',
                truncated INTEGER NOT NULL DEFAULT 0,
                extracted_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (account, message_id, attachment_id)
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_account_sent"
            " ON messages(account, sent_at DESC)"
        )

    def upsert(self, messages: list[Message]) -> int:
        changed = 0
        with self.connect() as connection:
            for message in messages:
                payload = json.dumps(message.to_dict(), ensure_ascii=False, sort_keys=True)
                digest = hashlib.sha256(payload.encode()).hexdigest()
                before = connection.total_changes
                connection.execute(
                    """
                    INSERT INTO messages (
                        account, provider_id, thread_id, sent_at, folder,
                        sender, subject, payload_json, payload_sha256
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(account, provider_id) DO UPDATE SET
                        thread_id=excluded.thread_id,
                        sent_at=excluded.sent_at,
                        folder=excluded.folder,
                        sender=excluded.sender,
                        subject=excluded.subject,
                        payload_json=excluded.payload_json,
                        payload_sha256=excluded.payload_sha256
                    WHERE messages.payload_sha256 != excluded.payload_sha256
                    """,
                    (
                        message.account,
                        message.id,
                        message.thread_id,
                        message.sent_at,
                        message.folder,
                        message.sender,
                        message.subject,
                        payload,
                        digest,
                    ),
                )
                changed += int(connection.total_changes > before)
        return changed

    def list_messages(self, account: str | None = None, limit: int = 20) -> list[dict[str, object]]:
        try:
            limit = int(limit)
        except (TypeError, ValueError):
            limit = 20
        limit = max(1, min(limit, 100))
        query = (
            "SELECT account, provider_id, thread_id, sent_at, folder, sender, subject, payload_json "
            "FROM messages"
        )
        params: list[object] = []
        if account:
            query += " WHERE account = ?"
            params.append(account)
        query += " ORDER BY sent_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            rows = [dict(row) for row in connection.execute(query, params)]
        for row in rows:
            payload = json.loads(str(row.pop("payload_json")))
            row["attachments"] = payload.get("attachments", [])
        return rows

    def get_message(self, account: str, message_id: str) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT payload_json FROM messages WHERE account = ? AND provider_id = ?",
                (account, message_id),
            ).fetchone()
        return json.loads(row["payload_json"]) if row else None

    def create_draft_candidate(
        self,
        account: str,
        to: list[str],
        subject: str,
        body: str,
        in_reply_to: str | None = None,
    ) -> int:
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO draft_candidates (account, to_json, subject, body, in_reply_to) VALUES (?, ?, ?, ?, ?)",
                (account, json.dumps(to), subject, body, in_reply_to),
            )
            return int(cursor.lastrowid)

    def build_knowledge_view(self) -> dict[str, object]:
        with self.connect() as connection:
            total = connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
            grouped = connection.execute(
                "SELECT account, sender, COUNT(*) AS n FROM messages"
                " GROUP BY account, sender ORDER BY n DESC, account, sender"
            ).fetchall()
        contacts = [
            {"account": row["account"], "address": row["sender"], "message_count": int(row["n"])}
            for row in grouped
        ]
        return {
            "schema_version": 1,
            "derived_from": "local_archive",
            "message_count": int(total),
            "contacts": contacts,
        }

    def create_local_artifact(self, kind: str, title: str, body: str) -> int:
        if kind not in {"analysis", "summary", "contact_note"}:
            raise ValueError("unsupported local artifact kind")
        with self.connect() as connection:
            cursor = connection.execute(
                "INSERT INTO local_artifacts (kind, title, body) VALUES (?, ?, ?)",
                (kind, title, body),
            )
            return int(cursor.lastrowid)

    def get_local_artifact(self, artifact_id: int) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT id, kind, title, body, created_at FROM local_artifacts WHERE id = ?",
                (artifact_id,),
            ).fetchone()
        return dict(row) if row else None

    def store_attachment_text(
        self,
        account: str,
        message_id: str,
        attachment_id: str,
        source_sha256: str,
        extractor: str | None,
        status: str,
        text: str,
        truncated: bool,
    ) -> None:
        with self.connect() as connection:
            connection.execute(
                """
                INSERT INTO attachment_texts (
                    account, message_id, attachment_id, source_sha256,
                    extractor, status, text, truncated
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account, message_id, attachment_id) DO UPDATE SET
                    source_sha256=excluded.source_sha256,
                    extractor=excluded.extractor,
                    status=excluded.status,
                    text=excluded.text,
                    truncated=excluded.truncated,
                    extracted_at=CURRENT_TIMESTAMP
                """,
                (
                    account,
                    message_id,
                    attachment_id,
                    source_sha256,
                    extractor,
                    status,
                    text,
                    int(truncated),
                ),
            )

    def get_attachment_text(
        self, account: str, message_id: str, attachment_id: str
    ) -> dict[str, object] | None:
        with self.connect() as connection:
            row = connection.execute(
                "SELECT account, message_id, attachment_id, source_sha256, extractor,"
                " status, text, truncated, extracted_at FROM attachment_texts"
                " WHERE account = ? AND message_id = ? AND attachment_id = ?",
                (account, message_id, attachment_id),
            ).fetchone()
        if row is None:
            return None
        record = dict(row)
        record["truncated"] = bool(record["truncated"])
        return record

    def verify(self) -> dict[str, object]:
        mismatches = 0
        message_count = 0
        with self.connect() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            for row in connection.execute("SELECT payload_json, payload_sha256 FROM messages"):
                message_count += 1
                actual = hashlib.sha256(row["payload_json"].encode()).hexdigest()
                mismatches += int(actual != row["payload_sha256"])
            cached = connection.execute(
                "SELECT COUNT(*) FROM attachment_texts"
            ).fetchone()[0]
            orphaned = connection.execute(
                """
                SELECT COUNT(*) FROM attachment_texts AS cached
                WHERE NOT EXISTS (
                    SELECT 1 FROM messages
                    WHERE messages.account = cached.account
                      AND messages.provider_id = cached.message_id
                )
                """
            ).fetchone()[0]
        return {
            "sqlite": integrity,
            "messages": message_count,
            "hash_mismatches": mismatches,
            "attachment_texts": int(cached),
            "orphaned_attachment_texts": int(orphaned),
        }
