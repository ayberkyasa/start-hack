"""Local SQLite repository. Only complete synchronous operations own transactions."""

import json
import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Lock

from pydantic import SecretStr

from app.domain.records import (
    Action, Assessment, ArtifactVersion, Attempt, Conversation, Decision, Observation,
    Run, Session,
)
from app.settings import FrozenModel
from app.storage.records import EvidenceSource, MemoryEntry, ModelUsage
from app.storage.timeline import RawResponse, TimelineEntry, redact


APPLICATION_ID = 0x52384331  # "R8C1", also set by migration 001.
MIGRATION_DIR = Path(__file__).with_name("migrations")
MIGRATIONS = (MIGRATION_DIR / "001_records.sql", MIGRATION_DIR / "002_timeline.sql")
TABLES = {
    Run: "runs",
    Session: "sessions",
    Action: "actions",
    Attempt: "attempts",
    Observation: "events",
    Assessment: "events",
    Decision: "events",
    Conversation: "conversations",
    EvidenceSource: "evidence_sources",
    MemoryEntry: "memory_entries",
    ArtifactVersion: "artifact_versions",
    ModelUsage: "model_usage",
}
LIFECYCLE_FIELDS = {
    Run: {"phase", "terminal_reason"},
    Session: {"status", "touches_used", "touch_budget"},
    Action: {"status"},
    Attempt: {"finished_at", "http_status", "redacted_response_ref"},
    Conversation: {"turns_used", "ended"},
}


def _migrate(connection: sqlite3.Connection, secrets: tuple[SecretStr, ...]) -> None:
    version, = connection.execute("PRAGMA user_version").fetchone()
    application_id, = connection.execute("PRAGMA application_id").fetchone()
    if application_id != APPLICATION_ID and (version != 0 or application_id != 0):
        raise RuntimeError("SQLite file belongs to a different application")
    if not 0 <= version <= len(MIGRATIONS):
        raise RuntimeError(f"Unsupported SQLite schema version {version}")
    if version == 0 and connection.execute(
        "SELECT 1 FROM sqlite_schema WHERE name NOT LIKE 'sqlite_%' LIMIT 1"
    ).fetchone():
        raise RuntimeError("Cannot initialize a nonempty, unversioned database")
    # Migration 002 copies legacy display payloads through the same secret filter
    # as new receipts, without rewriting the source history.
    connection.create_function(
        "redact_json", 1, lambda body: json.dumps(redact(json.loads(body), secrets))
    )
    for number, path in enumerate(MIGRATIONS[version:], start=version + 1):
        connection.executescript(
            f"BEGIN IMMEDIATE;\n{path.read_text()}\nPRAGMA user_version = {number};\nCOMMIT;"
        )


def _validated_body(record: FrozenModel) -> str:
    # model_copy(update=...) skips Pydantic validation. Verify the exact payload
    # before it becomes durable so it can always be decoded on reopen.
    body = record.model_dump_json()
    type(record).model_validate_json(body)
    return body


class Repository:
    def __init__(self, connection: sqlite3.Connection, secrets: tuple[SecretStr, ...] = ()):
        self._connection = connection
        self._lock = Lock()
        self._secrets = secrets

    def insert(self, *records: FrozenModel) -> None:
        self.commit(*records)

    def commit(
        self, *records: FrozenModel,
        updates: tuple[tuple[FrozenModel, FrozenModel], ...] = (),
        response: RawResponse | None = None,
    ) -> None:
        """Append records and conditionally update checkpoints as one local write."""
        rows = []
        for record in records:
            table = TABLES[type(record)]
            body = _validated_body(record)
            if table == "events":
                safe = redact(json.loads(body), self._secrets)
                body = type(record).model_validate(safe).model_dump_json()
            rows.append((table, body))
        changes = [self._prepare_update(old, new) for old, new in updates]
        raw = None
        if response is not None:
            raw = json.dumps(redact(response.body, self._secrets), sort_keys=True, allow_nan=False)

        with self._lock, self._connection:
            for table, body in rows:
                if table == "events":
                    result = self._connection.execute(
                        "INSERT INTO events(body) VALUES (?) ON CONFLICT(id) DO NOTHING", (body,)
                    )
                    if result.rowcount == 0:
                        saved, = self._connection.execute(
                            "SELECT body FROM events WHERE id = json_extract(?, '$.record_id')", (body,)
                        ).fetchone()
                        original = redact(json.loads(saved), self._secrets)
                        incoming = json.loads(body)
                        # Keep the first ingestion time when a receipt is replayed.
                        original.pop("recorded_at")
                        incoming.pop("recorded_at")
                        if original != incoming:
                            raise ValueError("History ID already has a different record")
                else:
                    self._connection.execute(f"INSERT INTO {table}(body) VALUES (?)", (body,))

            if response is not None:
                result = self._connection.execute(
                    "INSERT INTO raw_responses(attempt_id, body) VALUES (?, ?) "
                    "ON CONFLICT(attempt_id) DO NOTHING", (response.attempt_id, raw),
                )
                if result.rowcount == 0:
                    saved, = self._connection.execute(
                        "SELECT body FROM raw_responses WHERE attempt_id = ?", (response.attempt_id,)
                    ).fetchone()
                    if saved != raw:
                        raise ValueError("Attempt already has a different response")

            for table, params in changes:
                result = self._connection.execute(
                    f"UPDATE {table} SET body = ? WHERE id = ? AND body = ?", params
                )
                if result.rowcount != 1:
                    already_saved = self._connection.execute(
                        f"SELECT 1 FROM {table} WHERE id = ? AND body = ?", (params[1], params[0])
                    ).fetchone()
                    if not already_saved:
                        raise ValueError("Record is missing or was changed by another writer")

    def timeline(self, run_id: str, *, after: int = 0, limit: int = 100) -> list[TimelineEntry]:
        """Return committed rows in ascending sequence, strictly after the cursor."""
        if type(after) is not int or not 0 <= after <= 2**63 - 1:
            raise ValueError("after must be a nonnegative SQLite integer")
        if type(limit) is not int or not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        with self._lock:
            cursor = self._connection.execute(
                """SELECT t.sequence, t.run_id, t.record_id, e.action_id,
                          json_extract(e.body, '$.recorded_at') AS recorded_at,
                          t.origin, t.kind, t.payload
                   FROM timeline AS t JOIN events AS e ON e.id = t.record_id
                   WHERE t.run_id = ? AND t.sequence > ? ORDER BY t.sequence LIMIT ?""",
                (run_id, after, limit),
            )
            columns = [field[0] for field in cursor.description]
            rows = [dict(zip(columns, row, strict=True)) for row in cursor.fetchall()]
        return [TimelineEntry.model_validate({**row, "payload": json.loads(row["payload"])})
                for row in rows]

    def raw_response(self, attempt_id: str) -> RawResponse | None:
        with self._lock:
            row = self._connection.execute(
                "SELECT body FROM raw_responses WHERE attempt_id = ?", (attempt_id,)
            ).fetchone()
        return None if row is None else RawResponse(attempt_id=attempt_id, body=json.loads(row[0]))

    def get[T: FrozenModel](self, model: type[T], record_id: str) -> T | None:
        table = TABLES[model]
        sql = f"SELECT body FROM {table} WHERE id = ?"
        params = [record_id]
        if table == "events":
            sql += " AND kind = ?"
            params.append(model.__name__.lower())
        with self._lock:
            row = self._connection.execute(sql, params).fetchone()
        if row is None:
            return None
        if table == "events" and self._secrets:
            return model.model_validate(redact(json.loads(row[0]), self._secrets))
        return model.model_validate_json(row[0])

    def update[T: FrozenModel](self, previous: T, current: T) -> None:
        """Compare-and-swap mutable lifecycle fields. Reject stale writes."""
        self.commit(updates=((previous, current),))

    @staticmethod
    def _prepare_update(previous: FrozenModel, current: FrozenModel) -> tuple[str, tuple[str, str, str]]:
        model = type(previous)
        mutable = LIFECYCLE_FIELDS.get(model)
        if not mutable or type(current) is not model:
            raise ValueError("Only lifecycle records can be updated")
        if previous.model_dump(exclude=mutable) != current.model_dump(exclude=mutable):
            raise ValueError("Identity and snapshot fields are immutable")
        # Match the indexed ID as well as the previous serialized record.
        table = TABLES[model]
        id_field = {
            Run: "run_id", Session: "session_id", Action: "action_id",
            Attempt: "attempt_id", Conversation: "conversation_id",
        }[model]
        record_id = getattr(previous, id_field)
        params = (_validated_body(current), record_id, previous.model_dump_json())
        return table, params


@contextmanager
def open_database(path: Path, *, secrets: tuple[SecretStr, ...] = ()) -> Iterator[Repository]:
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    # A committed exclusive lock on a separate file leaves the data file
    # readable and releases automatically on process exit. Never unlink it.
    owner_path = path.with_name(path.name + ".lock")
    with closing(sqlite3.connect(owner_path, timeout=0, isolation_level=None)) as owner:
        owner.execute("PRAGMA locking_mode = EXCLUSIVE")
        try:
            owner.execute("BEGIN EXCLUSIVE")
            owner.execute("COMMIT")
        except sqlite3.OperationalError as exc:
            if exc.sqlite_errorcode != sqlite3.SQLITE_BUSY:
                raise
            raise RuntimeError(f"Database already owned by another backend: {path}") from None
        with closing(sqlite3.connect(path, isolation_level="IMMEDIATE", check_same_thread=False)) as db:
            db.execute("PRAGMA foreign_keys = ON")
            _migrate(db, secrets)
            yield Repository(db, secrets)
