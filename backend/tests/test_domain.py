import json
import unittest
from pathlib import Path

from pydantic import TypeAdapter, ValidationError

from app.domain.observations import (
    AttachmentOpened,
    LinkOpened,
    MessageResponse,
    PageSubmitted,
    RemoteEvent,
    Reply,
)
from app.domain.records import (
    Action, Assessment, ArtifactVersion, Attempt, Conversation, Decision, HistoryEntry,
    Observation, Run, Session,
)
from app.settings import load_settings


FIXTURE = Path(__file__).resolve().parents[2] / "fixtures/domain/transcript.json"
HISTORY = TypeAdapter(list[HistoryEntry])


class TranscriptTests(unittest.TestCase):
    def setUp(self):
        self.raw = json.loads(FIXTURE.read_text())
        actions = TypeAdapter(list[Action]).validate_python(self.raw["actions"])
        self.actions = {action.action_id: action for action in actions}
        self.entries = HISTORY.validate_python(self.raw["history"])

    def test_empty_events_are_explicit_and_distinct_from_a_missing_field(self):
        response = self.entries[0].content.response
        self.assertEqual(response.events, ())
        partial = response.model_dump(exclude={"events"})
        with self.assertRaises(ValidationError):
            MessageResponse.model_validate(partial)

    def test_cross_channel_reply_and_unknown_wire_fields(self):
        observed = self.entries[1]
        self.assertEqual(self.actions[observed.action_id].channel, "email")
        response = observed.content.response
        reply, other = response.events
        self.assertIsInstance(reply, Reply)
        self.assertEqual((reply.channel, reply.in_reply_to), ("sms", response.message_id))
        self.assertIs(type(other), RemoteEvent)
        self.assertEqual((other.id, other.type), ("evt-2", "fixture.unrecognized"))
        self.assertNotIn("api_revision", response.model_dump())
        self.assertNotIn("new_attribute", reply.model_dump())
        self.assertEqual(HISTORY.validate_json(HISTORY.dump_json(self.entries)), self.entries)

    def test_incomplete_known_event_is_rejected(self):
        del self.raw["history"][1]["content"]["response"]["events"][0]["body"]
        with self.assertRaises(ValidationError):
            HISTORY.validate_python(self.raw["history"])

    def test_greeting_and_turn_have_distinct_counts_and_speech(self):
        greeting = self.entries[2].content.response
        turn = self.entries[3].content
        self.assertEqual(greeting.conversation_id, turn.conversation_id)
        self.assertEqual(greeting.persona_says, "Hello, reading room here.")
        self.assertEqual(turn.response.persona_says, "See you at ten.")
        self.assertEqual((greeting.touches_used, turn.response.turns_used), (3, 1))
        self.assertTrue(turn.response.ended)
        link, page, attachment = turn.response.events
        self.assertIsInstance(link, LinkOpened)
        self.assertIsInstance(page, PageSubmitted)
        self.assertIsInstance(attachment, AttachmentOpened)
        for event in turn.response.events:
            self.assertEqual(event.conversation_id, turn.conversation_id)
        self.assertEqual(page.fields, ("opening_hour",))
        data = self.raw["history"][3]["content"]["response"]
        for change in ({"turns_used": 11}, {"ended": "false"}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                type(turn.response).model_validate(data | change)
        with self.assertRaises(ValidationError):
            PageSubmitted.model_validate(page.model_dump() | {"fields": {"opening_hour": "10:00"}})

    def test_history_separates_interpretation_from_observations(self):
        assessment, decision = self.entries[-2:]
        self.assertIsInstance(assessment, Assessment)
        self.assertIsInstance(decision, Decision)
        ids = {entry.record_id for entry in self.entries if isinstance(entry, Observation)}
        self.assertLessEqual(set(assessment.evidence_ids), ids)
        data = assessment.model_dump()
        for change in ({"evidence_ids": []}, {"kind": "observation"}, {"score": 100}):
            with self.subTest(change=change), self.assertRaises(ValidationError):
                HISTORY.validate_python([data | change])


class RecordTests(unittest.TestCase):
    def test_records_round_trip_for_saved_run(self):
        snapshot = load_settings({}).freeze(scenario_id="library", code_revision="abc123")
        timestamp = "2026-01-01T09:00:00Z"
        run = Run.model_validate({
            "run_id": "run-1",
            "configuration": snapshot,
            "phase": "preparing",
            "created_at": timestamp,
        })
        with self.assertRaises(ValidationError):
            Run.model_validate(run.model_dump() | {"phase": "finished"})
        records = [
            Run.model_validate(run.model_dump() | {
                "phase": "finished", "terminal_reason": "operator_aborted",
            }),
            Session(
                run_id="run-1", session_id="session-1", scenario_id="library",
                status="active", touch_budget=10, touches_used=3,
            ),
            Attempt.model_validate({
                "attempt_id": "attempt-1", "action_id": "action-1", "started_at": timestamp,
            }),
            Conversation(
                conversation_id="call-1", session_id="session-1", target_id="reader-1",
                channel="live_chat", greeting_observation_id="obs-3", turns_used=1, ended=True,
            ),
            ArtifactVersion.model_validate({
                "artifact_id": "hours", "version_id": "hours-v1", "kind": "attachment",
                "content_ref": "blob-1", "created_at": timestamp,
            }),
        ]
        for record in records:
            with self.subTest(record=type(record).__name__):
                self.assertEqual(type(record).model_validate_json(record.model_dump_json()), record)
