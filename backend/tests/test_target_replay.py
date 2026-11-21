import os
import unittest
from unittest.mock import patch

from app.target.replay import LibraryReplay, ReplayClient


class LibraryReplayTests(unittest.TestCase):
    def test_full_recording_is_reproducible_offline(self):
        with patch.dict(os.environ, {}, clear=True), patch(
            "socket.socket.connect", side_effect=AssertionError("unexpected network call")
        ):
            def read():
                client: ReplayClient = LibraryReplay()
                return [client.advance(step) for step in client.steps()], client.events(), client.session()

            first = read()
            self.assertEqual(first, read())
            self.assertEqual(first[2]["status"], "ended")
            self.assertEqual(first[2]["touches_used"], 3)
            self.assertEqual(len(first[1]), 5)

    def test_discovery_and_returned_objects_are_isolated(self):
        client = LibraryReplay()
        self.assertIsNone(client.session())
        scenario, = client.scenarios()
        self.assertEqual(scenario["kind"], "mock")
        self.assertEqual(scenario["targets"][0]["id"], "reader-1")
        self.assertIn("live_chat", client.channels())
        scenario["targets"].clear()
        opened = client.advance("open")
        opened.body["touches_used"] = 123
        self.assertEqual(client.advance("open").body["touches_used"], 0)
        self.assertEqual(client.session()["touches_used"], 0)
        self.assertEqual(len(client.scenarios()[0]["targets"]), 1)
        self.assertIsNone(LibraryReplay().session())

    def test_unknown_and_out_of_order_steps_preserve_state(self):
        client = LibraryReplay()
        with self.assertRaises(KeyError):
            client.advance("unknown")
        with self.assertRaisesRegex(ValueError, "open"):
            client.advance("close")
        self.assertEqual(client.events(), [])
        self.assertIsNone(client.session())
        client.advance("open")
        with self.assertRaisesRegex(ValueError, "hours-file"):
            client.advance("notice")
        self.assertEqual(client.session()["status"], "active")

    def test_repeated_contact_reuses_reply_without_spending_a_touch(self):
        client = LibraryReplay()
        for step in ("open", "hours-file", "hours-page"):
            client.advance(step)
        notice = client.advance("notice")
        self.assertEqual(notice.body["events"], [])
        first = client.advance("hours-question")
        self.assertEqual(first.request["channel"], "email")
        self.assertEqual(first.body["events"][0]["channel"], "sms")
        before = client.events()
        repeat = client.advance("hours-question-again")
        self.assertIsNotNone(first.request_key)
        self.assertEqual(repeat.request_key, first.request_key)
        self.assertEqual((repeat.request, repeat.body), (first.request, first.body))
        self.assertEqual(client.events(), before)
        self.assertEqual(client.session()["touches_used"], 2)
        before[0]["body"] = "edited outside the client"
        self.assertNotEqual(before, client.events())

    def test_artifact_receipts_call_end_and_budget_limit(self):
        client = LibraryReplay()
        seen = {step: client.advance(step) for step in client.steps()}
        self.assertEqual(seen["chat"].body["persona_says"], "Hello, reading room here.")
        turn = seen["goodbye"].body
        self.assertEqual(turn["turns_used"], 1)
        self.assertTrue(turn["ended"])
        link, page, attachment = turn["events"]
        self.assertEqual(link["url"], seen["hours-page"].request["url"])
        self.assertEqual(page["page_id"], seen["hours-page"].body["page_id"])
        self.assertEqual(page["fields"], ["opening_hour"])
        self.assertEqual(attachment["filename"], seen["hours-file"].request["filename"])
        self.assertEqual(seen["after-goodbye"].error_status, 409)
        self.assertEqual(seen["at-limit"].error_status, 409)
        self.assertEqual(client.session()["touches_used"], seen["chat"].body["touches_used"])
        self.assertEqual(client.events()[-3:], turn["events"])
