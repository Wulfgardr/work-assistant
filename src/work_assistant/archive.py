from __future__ import annotations

from collections import Counter
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
        query = "SELECT account, provider_id, thread_id, sent_at, folder, sender, subject FROM messages"
        params: list[object] = []
        if account:
            query += " WHERE account = ?"
            params.append(account)
        query += " ORDER BY sent_at DESC LIMIT ?"
        params.append(limit)
        with self.connect() as connection:
            return [dict(row) for row in connection.execute(query, params)]

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
            rows = connection.execute("SELECT account, sender, payload_json FROM messages").fetchall()
        contacts: Counter[tuple[str, str]] = Counter()
        for row in rows:
            contacts[(row["account"], row["sender"])] += 1
        return {
            "schema_version": 1,
            "derived_from": "local_archive",
            "message_count": len(rows),
            "contacts": [
                {"account": account, "address": address, "message_count": count}
                for (account, address), count in sorted(contacts.items(), key=lambda item: (-item[1], item[0]))
            ],
        }

    def verify(self) -> dict[str, object]:
        mismatches = 0
        with self.connect() as connection:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            rows = connection.execute("SELECT payload_json, payload_sha256 FROM messages").fetchall()
        for row in rows:
            actual = hashlib.sha256(row["payload_json"].encode()).hexdigest()
            mismatches += int(actual != row["payload_sha256"])
        return {"sqlite": integrity, "messages": len(rows), "hash_mismatches": mismatches}
