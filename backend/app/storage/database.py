"""Local SQLite repository. Only complete synchronous operations own transactions."""

import sqlite3
from collections.abc import Iterator
from contextlib import closing, contextmanager
from pathlib import Path
from threading import Lock

from app.domain.records import (
    Action, Assessment, ArtifactVersion, Attempt, Conversation, Decision, Observation,
    Run, Session,
)
from app.settings import FrozenModel
from app.storage.records import EvidenceSource, MemoryEntry, ModelUsage


APPLICATION_ID = 0x52384331  # "R8C1", also set by migration 001.
MIGRATIONS = (Path(__file__).with_name("migrations") / "001_records.sql",)
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


def _migrate(connection: sqlite3.Connection) -> None:
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
    def __init__(self, connection: sqlite3.Connection):
        self._connection = connection
        self._lock = Lock()

    def insert(self, *records: FrozenModel) -> None:
        # Prepare outside the transaction so validation and serialization cannot
        # extend the time the database is locked.
        rows = [(TABLES[type(record)], _validated_body(record)) for record in records]
        with self._lock, self._connection:
            for table, body in rows:
                self._connection.execute(f"INSERT INTO {table}(body) VALUES (?)", (body,))

    def get[T: FrozenModel](self, model: type[T], record_id: str) -> T | None:
        table = TABLES[model]
        sql = f"SELECT body FROM {table} WHERE id = ?"
        params = [record_id]
        if table == "events":
            sql += " AND kind = ?"
            params.append(model.__name__.lower())
        with self._lock:
            row = self._connection.execute(sql, params).fetchone()
        return None if row is None else model.model_validate_json(row[0])

    def update[T: FrozenModel](self, previous: T, current: T) -> None:
        """Compare-and-swap mutable lifecycle fields. Reject stale writes."""
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
        with self._lock, self._connection:
            result = self._connection.execute(
                f"UPDATE {table} SET body = ? WHERE id = ? AND body = ?", params
            )
            if result.rowcount != 1:
                raise ValueError("Record is missing or was changed by another writer")


@contextmanager
def open_database(path: Path) -> Iterator[Repository]:
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
            _migrate(db)
            yield Repository(db)
