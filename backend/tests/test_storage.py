import asyncio
import json
import sqlite3
import subprocess
import sys
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import TypeAdapter, ValidationError

from app.domain.records import (
    Action, Assessment, ArtifactVersion, Attempt, Conversation, Decision, HistoryEntry,
    Observation, Run, RunPhase, Session,
)
from app.settings import load_settings
from app.storage.database import open_database
from app.storage.records import EvidenceSource, MemoryEntry, ModelUsage


BACKEND = Path(__file__).resolve().parents[1]
TRANSCRIPT = BACKEND.parent / "fixtures/domain/transcript.json"
STAMP = "2026-01-01T09:00:00Z"


def run_record(run_id="r1"):
    snapshot = load_settings({}).freeze(scenario_id="library", code_revision="abc123")
    return Run.model_validate({
        "run_id": run_id, "configuration": snapshot, "phase": "preparing", "created_at": STAMP,
    })


def session_record(session_id="s1", run_id="r1"):
    return Session(
        session_id=session_id, run_id=run_id, scenario_id="library", status="active",
        touch_budget=10, touches_used=0,
    )


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / "data" / "test.sqlite3"

    def test_all_record_families_survive_reopen(self):
        fixture = json.loads(TRANSCRIPT.read_text())
        actions = TypeAdapter(list[Action]).validate_python(fixture["actions"])
        history = TypeAdapter(list[HistoryEntry]).validate_python(fixture["history"])
        records = [
            ("run-1", run_record("run-1")),
            ("session-1", session_record("session-1", "run-1")),
            *((a.action_id, a) for a in actions),
            *((e.record_id, e) for e in history),
            ("attempt-1", Attempt.model_validate({
                "attempt_id": "attempt-1", "action_id": "action-1", "started_at": STAMP,
            })),
            ("call-1", Conversation(
                conversation_id="call-1", session_id="session-1", target_id="reader-1",
                channel="live_chat", greeting_observation_id="obs-3", turns_used=1, ended=True,
            )),
            ("ver-1", ArtifactVersion.model_validate({
                "artifact_id": "hours", "version_id": "ver-1", "kind": "message",
                "content_ref": "body-1", "created_at": STAMP,
            })),
            ("src-1", EvidenceSource.model_validate({
                "source_id": "src-1", "uri": "https://library.example/hours",
                "retrieved_at": STAMP, "excerpt": "Opens at ten.",
            })),
            ("note-1", MemoryEntry.model_validate({
                "entry_id": "note-1", "session_id": "session-1", "source_id": "src-1",
                "recorded_at": STAMP, "text": "Reading room hours.",
            })),
            ("usage-1", ModelUsage.model_validate({
                "usage_id": "usage-1", "run_id": "run-1", "recorded_at": STAMP,
                "provider_id": "mock", "model_id": "book", "duration_ms": 3,
            })),
        ]
        with open_database(self.path) as repo:
            repo.insert(*(record for _, record in records))
        with open_database(self.path) as repo:
            for record_id, record in records:
                self.assertEqual(repo.get(type(record), record_id), record)
            self.assertIsNone(repo.get(Assessment, "obs-3"))
            self.assertIsNone(repo.get(Decision, "obs-3"))
            self.assertIsInstance(repo.get(Observation, "obs-3"), Observation)

    def test_ownership_and_related_records_are_atomic(self):
        with open_database(self.path) as repo:
            repo.insert(run_record(), run_record("r2"), session_record())
            for conflict in (session_record("s1", "r2"), session_record("s2", "r1")):
                with self.subTest(conflict=conflict), self.assertRaises(sqlite3.IntegrityError):
                    repo.insert(run_record("rolled-back"), conflict)
                self.assertIsNone(repo.get(Run, "rolled-back"))
            action = Action(action_id="a1", run_id="r2", session_id="s1", operation="message",
                            status="succeeded", request_body_ref="body")
            with self.assertRaises(sqlite3.IntegrityError):
                repo.insert(action)
            self.assertEqual(repo.get(Session, "s1"), session_record())
            self.assertIsNone(repo.get(Action, "a1"))

    def test_updates_require_original_snapshot_and_current_state(self):
        original = run_record()
        active = original.model_copy(update={"phase": RunPhase.READY})
        with open_database(self.path) as repo:
            repo.insert(original)
            repo.update(original, active)
            with self.assertRaisesRegex(ValueError, "changed"):
                repo.update(original, original)
            with self.assertRaisesRegex(ValueError, "immutable"):
                repo.update(active, active.model_copy(update={"run_id": "r2"}))
            with self.assertRaises(ValidationError):
                repo.update(active, active.model_copy(update={"phase": RunPhase.FINISHED}))
            self.assertEqual(repo.get(Run, "r1"), active)

    def test_second_process_refused_and_crashed_owner_releases_lock(self):
        source = (
            "import os, sys\nfrom pathlib import Path\n"
            "from app.storage.database import open_database\n"
            "with open_database(Path(sys.argv[1])):\n    os._exit(0)\n"
        )

        def start_child():
            return subprocess.run(
                [sys.executable, "-c", source, str(self.path)], cwd=BACKEND,
                capture_output=True, text=True, timeout=10,
            )

        with open_database(self.path) as repo:
            repo.insert(run_record())
            denied = start_child()
            self.assertNotEqual(denied.returncode, 0)
            self.assertIn("already owned", denied.stderr)
        crashed = start_child()
        self.assertEqual(crashed.returncode, 0, crashed.stderr)
        with open_database(self.path) as repo:
            self.assertEqual(repo.get(Run, "r1"), run_record())

    def test_failed_migration_rolls_back_ddl_and_version(self):
        bad = self.path.parent.parent / "bad.sql"
        bad.write_text("CREATE TABLE partial(id INTEGER); INVALID SQL;")
        with patch("app.storage.database.MIGRATIONS", (bad,)):
            with self.assertRaises(sqlite3.OperationalError):
                with open_database(self.path):
                    self.fail("invalid schema opened")
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("PRAGMA user_version").fetchone(), (0,))
            self.assertEqual(db.execute("SELECT name FROM sqlite_schema").fetchall(), [])
        with open_database(self.path) as repo:
            repo.insert(run_record())
        with closing(sqlite3.connect(self.path)) as db:
            db.execute("PRAGMA user_version = 99")
        with self.assertRaisesRegex(RuntimeError, "99"):
            with open_database(self.path):
                self.fail("future schema opened")

    def test_no_write_transaction_survives_into_an_external_wait(self):
        async def probe():
            pending = asyncio.Event()
            done = asyncio.Event()

            async def caller(repo):
                repo.insert(run_record())
                pending.set()
                await done.wait()
                repo.insert(session_record())

            with open_database(self.path) as repo:
                writer = asyncio.create_task(caller(repo))
                await asyncio.wait_for(pending.wait(), timeout=3)
                try:
                    with closing(sqlite3.connect(self.path, timeout=0)) as peer:
                        peer.execute("BEGIN IMMEDIATE")
                        self.assertEqual(peer.execute("SELECT id FROM runs").fetchone(), ("r1",))
                        peer.rollback()
                finally:
                    done.set()
                    await writer
        asyncio.run(probe())
