import json
import unittest
from unittest.mock import patch

from pydantic import SecretStr

from app.target.observer import ReadError, ReadFailure
from app.target.remote_observer import RemoteObserver


class RemoteObserverTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.key = "test-team-key"
        self.client = RemoteObserver(SecretStr(self.key), timeout_seconds=17)
        self.https = self.enterContext(patch("app.target.remote_observer.HTTPSConnection"))
        self.connection = self.https.return_value
        self.response = self.connection.getresponse.return_value.__enter__.return_value
        self.response.status = 200

    async def test_documented_inspection_reads_and_locked_scenario(self):
        session = {"session_id": "s_1", "scenario_id": "practice", "touch_budget": 30,
                   "touches_used": 2, "status": "active"}
        for read, args, path, data in (
            (self.client.scenarios, (), "/scenarios", [{"id": "eval", "open": False}]),
            (self.client.channels, (), "/channels", ["email", "sms"]),
            (self.client.sessions, (), "/sessions", [session]),
            (self.client.session, ("s_1",), "/sessions/s_1", session),
            (self.client.history, ("s_1",), "/sessions/s_1/events", {"events": []}),
        ):
            with self.subTest(path=path):
                self.response.read.return_value = json.dumps(data).encode()
                result = await read(*args)
                self.https.assert_called_with("target-api.apps.01.cf.eu01.stackit.cloud", timeout=17)
                self.connection.request.assert_called_with("GET", "/v1" + path, headers={
                    "Authorization": "Bearer " + self.key, "Accept": "application/json",
                })
                if path == "/scenarios":
                    self.assertIs(result[0].open, False)
                if path.endswith("/events"):
                    self.assertEqual(result.events, ())
        self.assertEqual(self.connection.close.call_count, 5)

    async def test_errors_drop_remote_bodies_and_do_not_follow_redirects(self):
        for status, reason in (
            (302, ReadFailure.REJECTED), (401, ReadFailure.AUTHENTICATION), (403, ReadFailure.FORBIDDEN),
            (404, ReadFailure.NOT_FOUND), (429, ReadFailure.RATE_LIMIT), (503, ReadFailure.UNAVAILABLE),
        ):
            with self.subTest(status=status):
                self.response.status = status
                with self.assertRaises(ReadError) as ctx:
                    await self.client.sessions()
                self.assertEqual((ctx.exception.kind, ctx.exception.status), (reason, status))
                self.response.read.assert_not_called()
        self.assertEqual(self.connection.request.call_count, 6)

    async def test_secret_echo_invalid_response_and_network_failures(self):
        event = {"type": "reply", "id": "e-1", "channel": "email", "body": self.key}
        self.response.read.return_value = json.dumps({"events": [event]}).encode()
        self.assertNotIn(self.key, (await self.client.history("s_1")).model_dump_json())
        for body in (b"not-json", b'{"events": null}'):
            self.response.read.return_value = body
            with self.assertRaises(ReadError) as ctx:
                await self.client.history("s_1")
            self.assertEqual(ctx.exception.kind, ReadFailure.BAD_RESPONSE)
        for error, reason in ((TimeoutError(self.key), ReadFailure.TIMEOUT),
                              (OSError(self.key), ReadFailure.TRANSPORT)):
            self.connection.request.side_effect = error
            with self.assertRaises(ReadError) as ctx:
                await self.client.sessions()
            self.assertEqual(ctx.exception.kind, reason)
            self.assertNotIn(self.key, str(ctx.exception))

    async def test_paths_are_confined_and_session_ids_must_match(self):
        for invalid in ("", ".", "..", "../sessions", "a/b", "x\ny"):
            with self.assertRaises(ValueError):
                await self.client.history(invalid)
        self.https.assert_not_called()
        self.response.read.return_value = json.dumps({
            "session_id": "other", "scenario_id": "library", "status": "ended",
            "touch_budget": 3, "touches_used": 1,
        }).encode()
        with self.assertRaises(ReadError) as ctx:
            await self.client.session("s?query")
        self.assertEqual(self.connection.request.call_args.args[:2], ("GET", "/v1/sessions/s%3Fquery"))
        self.assertEqual(ctx.exception.kind, ReadFailure.BAD_RESPONSE)
