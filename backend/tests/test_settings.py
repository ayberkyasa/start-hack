import hashlib
import json
import os
import unittest
from unittest.mock import patch

from pydantic import ValidationError

from app.main import app
from app.settings import RunLimits, RunSnapshot, load_settings


def live_env(mode="practice"):
    return {
        "APP_MODE": mode,
        "APP_MODEL_ID": "fixture-model",
        "OPENAI_API_KEY": "test-only-model-key",
        "TARGET_API_TEAM_KEY": "test-only-team-key",
    }


def freeze(settings):
    return settings.freeze(scenario_id="fixture", code_revision="abc123")


class SettingsTests(unittest.TestCase):
    def test_empty_environment_defaults_to_local_mock(self):
        settings = load_settings({})
        self.assertEqual(settings.run.mode, "mock")
        self.assertEqual(settings.run.provider_id, "mock")
        self.assertIsNone(settings.openai_api_key)
        self.assertEqual(settings.run.limits.request_timeout_seconds, 120)

    def test_each_live_mode_requires_both_keys_and_a_model(self):
        for mode in ("practice", "eval"):
            env = live_env(mode)
            self.assertEqual(load_settings(env).run.provider_id, "openai")
            for key in ("APP_MODEL_ID", "TARGET_API_TEAM_KEY", "OPENAI_API_KEY"):
                for replacement in (None, "  "):
                    with self.subTest(mode=mode, key=key, replacement=replacement):
                        invalid = env.copy()
                        if replacement is None:
                            del invalid[key]
                        else:
                            invalid[key] = replacement
                        with self.assertRaisesRegex(ValueError, key) as error:
                            load_settings(invalid)
                        self.assertNotIn("test-only-", str(error.exception))

    def test_invalid_modes_and_provider_combinations(self):
        for mode, provider in (("bogus", "openai"), ("practice", "mock"),
                               ("mock", "openai"), ("eval", "unsupported")):
            with self.subTest(mode=mode, provider=provider), self.assertRaises(ValueError):
                load_settings({**live_env(mode), "APP_PROVIDER_ID": provider})

    def test_limits_are_bounded_and_strict(self):
        for field, metadata in RunLimits.model_json_schema()["properties"].items():
            for value in (metadata["minimum"] - 1, metadata["maximum"] + 1, True, "1"):
                with self.subTest(field=field, value=value), self.assertRaisesRegex(ValueError, field):
                    load_settings({"APP_RUN_LIMITS": json.dumps({field: value})})
        with self.assertRaisesRegex(ValueError, "eval maximum"):
            load_settings({**live_env("eval"), "APP_RUN_LIMITS": '{"contacts":11}'})

    def test_malformed_or_unknown_limits_do_not_echo_inputs(self):
        for raw in ('{"test-only-secret":1}', '["test-only-secret"]', 'test-only-secret'):
            with self.subTest(raw=raw), self.assertRaisesRegex(ValueError, "APP_RUN_LIMITS") as error:
                load_settings({"APP_RUN_LIMITS": raw})
            self.assertNotIn("test-only-", str(error.exception))

    def test_credentials_never_enter_public_serializations(self):
        settings = load_settings(live_env())
        snapshot = freeze(settings)
        for value in (repr(settings), settings.model_dump_json(), snapshot.canonical_json()):
            self.assertNotIn("test-only-", value)
            self.assertNotIn("api_key", value)
            self.assertNotIn("team_key", value)
        rotated = load_settings({**live_env(), "OPENAI_API_KEY": "rotated", "TARGET_API_TEAM_KEY": "new"})
        self.assertEqual(snapshot.canonical_json(), freeze(rotated).canonical_json())
        self.assertEqual(snapshot.config_hash(), freeze(rotated).config_hash())

    def test_snapshot_is_canonical_round_trippable_and_deeply_frozen(self):
        env = {"APP_RUN_LIMITS": '{"retries":0,"model_calls":2}'}
        first = freeze(load_settings(env))
        env["APP_RUN_LIMITS"] = '{"model_calls":2, "retries":0}'
        second = freeze(load_settings(env))
        self.assertEqual(first.canonical_json(), second.canonical_json())
        self.assertEqual(RunSnapshot.model_validate_json(first.canonical_json()), first)
        self.assertEqual(first.config_hash(), hashlib.sha256(first.canonical_json().encode()).hexdigest())
        with self.assertRaises(ValidationError):
            first.limits.retries = 1
        with self.assertRaises(ValidationError):
            first.model_id = "changed"
        for changes in ({"APP_MODEL_ID": "other"}, {"APP_RUN_LIMITS": '{"retries":1}'}):
            self.assertNotEqual(first.config_hash(), freeze(load_settings(env | changes)).config_hash())
        other_revision = load_settings(env).freeze(scenario_id="fixture", code_revision="def456")
        self.assertNotEqual(first.config_hash(), other_revision.config_hash())


class StartupTests(unittest.IsolatedAsyncioTestCase):
    async def test_startup_validates_before_serving_without_network(self):
        with patch("socket.socket.connect", side_effect=AssertionError("unexpected network call")):
            for env in ({}, live_env("eval")):
                with patch.dict(os.environ, env, clear=True):
                    async with app.router.lifespan_context(app):
                        self.assertEqual(app.state.settings, load_settings(env))
            with patch.dict(os.environ, {"APP_MODE": "eval"}, clear=True):
                with self.assertRaisesRegex(ValueError, "APP_MODEL_ID"):
                    async with app.router.lifespan_context(app):
                        self.fail("invalid settings reached startup")
