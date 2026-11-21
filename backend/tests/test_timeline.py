import json
import sqlite3
import unittest
from contextlib import closing
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from pydantic import SecretStr, TypeAdapter

from app.domain.records import Action, ActionStatus, Attempt, HistoryEntry, Run, RunPhase
from app.storage.database import MIGRATIONS, open_database
from app.storage.timeline import RawResponse
from test_storage import STAMP, TRANSCRIPT, run_record, session_record


class TimelineTests(unittest.TestCase):
    def setUp(self):
        self.path = Path(self.enterContext(TemporaryDirectory())) / "test.sqlite3"
        fixture = json.loads(TRANSCRIPT.read_text())
        self.actions = TypeAdapter(list[Action]).validate_python(fixture["actions"][:3])
        self.history = TypeAdapter(list[HistoryEntry]).validate_python(fixture["history"])
        self.run = run_record("run-1")

    def seed(self, repo):
        repo.insert(self.run, session_record("session-1", "run-1"), *self.actions)

    def test_remote_and_synthetic_dedup_across_replay_and_reopen(self):
        silence, message, greeting, turn = self.history[:4]
        turn = turn.model_copy(update={"action_id": None})
        with open_database(self.path) as repo:
            self.seed(repo)
            repo.insert(silence, message, greeting, turn)
            before = repo.timeline("run-1")
            self.assertEqual([e.kind for e in before], [
                "message", "message", "reply", "fixture.unrecognized", "greeting",
                "turn", "link.opened", "page.submitted", "attachment.opened",
            ])
            self.assertEqual(before[0].payload["event_count"], 0)
            self.assertEqual(before[1].payload["event_count"], 2)
            self.assertNotIn("events", before[1].payload["response"])
            self.assertEqual(before[2].origin, "remote")
            self.assertEqual(before[4].payload["response"]["persona_says"], "Hello, reading room here.")
        with open_database(self.path) as repo:
            repo.insert(silence, message, greeting, turn)
            replay = type(message).model_validate(message.model_dump() | {
                "recorded_at": "2026-01-02T00:00:00Z",
            })
            repo.insert(replay)
            for record in (silence, message, greeting, turn):
                repo.insert(record.model_copy(update={"record_id": "again-" + record.record_id}))
            self.assertEqual(repo.timeline("run-1"), before)

    def test_overlapping_remote_ids_are_counted_once_per_run(self):
        message = self.history[1]
        overlapping = message.model_dump(mode="json")
        overlapping["record_id"] = "obs-other"
        overlapping["action_id"] = None
        overlapping["content"]["response"]["message_id"] = "another-message"
        other = type(message).model_validate(overlapping)
        with open_database(self.path) as repo:
            self.seed(repo)
            repo.insert(message, other)
            self.assertEqual([e.kind for e in repo.timeline("run-1")],
                             ["message", "reply", "fixture.unrecognized", "message"])
            repo.insert(run_record("run-2"), other.model_copy(update={
                "run_id": "run-2", "record_id": "obs-another-run",
            }))
            self.assertEqual([e.kind for e in repo.timeline("run-2")],
                             ["message", "reply", "fixture.unrecognized"])

    def test_pagination_during_append_is_run_scoped_and_resumable(self):
        with open_database(self.path) as repo:
            self.seed(repo)
            repo.insert(*self.history[:2])
            repo.insert(run_record("run-2"))
            decision = self.history[-1]
            repo.insert(decision.model_copy(update={"run_id": "run-2", "record_id": "another"}))
            first = repo.timeline("run-1", limit=2)
            repo.insert(self.history[2], decision)
            rows = list(first)
            while page := repo.timeline("run-1", after=rows[-1].sequence, limit=1):
                rows.extend(page)
            self.assertEqual(rows, repo.timeline("run-1"))
            self.assertEqual(len(rows), 6)
            self.assertEqual(len({row.sequence for row in rows}), 6)
            self.assertTrue(all(row.run_id == "run-1" for row in rows))
        with open_database(self.path) as repo:
            self.assertEqual(repo.timeline("run-1", after=first[-1].sequence), rows[2:])
            for args in ({"after": -1}, {"after": True}, {"limit": 0}, {"limit": 1001}):
                with self.subTest(args=args), self.assertRaises(ValueError):
                    repo.timeline("run-1", **args)

    def test_redaction_preserves_unknown_diagnostic_fields_and_field_names(self):
        secret = "fake-key-XYZ"
        data = {
            "extra": {"revision": 42, "X-Team-Key": "secret-A", "api_key": "secret-B"},
            "headers": {"Authorization": "secret-C"}, "diagnostic": "Bearer secret-D",
            "note": "echo: " + secret, "fields": ["email", "password"],
            "nested": [{"name": "Authorization", "value": "secret-E"}],
            "page": {"fields": {"password": "secret-F"}}, "input_tokens": 27,
        }
        with open_database(self.path, secrets=(SecretStr(secret),)) as repo:
            self.seed(repo)
            attempt = Attempt(attempt_id="at1", action_id="action-1", started_at=STAMP)
            response = RawResponse(attempt_id="at1", body=data)
            repo.commit(attempt, response=response)
            repo.commit(response=response)
            saved = repo.raw_response("at1").body
            self.assertEqual(saved["extra"], {"revision": 42})
            self.assertEqual(saved["fields"], ["email", "password"])
            self.assertEqual(saved["input_tokens"], 27)
            self.assertEqual(saved["note"], "echo: [REDACTED]")
            self.assertNotIn("secret-", json.dumps(saved))
            with self.assertRaisesRegex(ValueError, "different response"):
                repo.commit(response=RawResponse(attempt_id="at1", body={"different": True}))
        self.assertNotIn(secret.encode(), self.path.read_bytes())
        self.assertNotIn(b"secret-", self.path.read_bytes())

    def test_receipt_action_and_checkpoint_commit_or_roll_back_together(self):
        action = self.actions[0].model_copy(update={"status": ActionStatus.IN_FLIGHT})
        completed = self.actions[0]
        ready = self.run.model_copy(update={"phase": RunPhase.READY})
        attempt = Attempt(attempt_id="at1", action_id=action.action_id, started_at=STAMP)
        response = RawResponse(attempt_id="at1", body={"events": []})
        with open_database(self.path) as repo:
            repo.insert(self.run, session_record("session-1", "run-1"), action, attempt)
            wrong = self.run.model_copy(update={"phase": RunPhase.STOPPING})
            with self.assertRaisesRegex(ValueError, "changed"):
                repo.commit(self.history[0], response=response, updates=((action, completed), (wrong, ready)))
            self.assertEqual(repo.timeline("run-1"), [])
            self.assertIsNone(repo.raw_response("at1"))
            self.assertEqual(repo.get(Action, action.action_id), action)
            updates = ((action, completed), (self.run, ready))
            repo.commit(self.history[0], response=response, updates=updates)
            repo.commit(self.history[0], response=response, updates=updates)
            self.assertEqual(len(repo.timeline("run-1")), 1)
            self.assertEqual(repo.raw_response("at1").body, {"events": []})
            self.assertEqual(repo.get(Run, "run-1"), ready)

    def test_version_one_backfill_and_append_only_guards(self):
        with patch("app.storage.database.MIGRATIONS", MIGRATIONS[:1]):
            with open_database(self.path) as repo:
                self.seed(repo)
                repo.insert(*self.history[:2])
                repo.insert(self.history[-1].model_copy(update={"summary": "Legacy fake-credential"}))
        with open_database(self.path, secrets=(SecretStr("fake-credential"),)) as repo:
            rows = repo.timeline("run-1")
            self.assertEqual(rows[-1].payload["summary"], "Legacy [REDACTED]")
            repo.insert(self.history[-1].model_copy(update={"summary": "Legacy fake-credential"}))
            self.assertEqual([e.kind for e in rows], ["message", "message", "reply", "fixture.unrecognized", "decision"])
            repo.insert(self.history[1])
            self.assertEqual(rows, repo.timeline("run-1"))
        with closing(sqlite3.connect(self.path)) as db:
            for sql in ("DELETE FROM timeline", "UPDATE timeline SET kind='changed'"):
                with self.subTest(sql=sql), self.assertRaisesRegex(sqlite3.IntegrityError, "append-only"):
                    db.execute(sql)
