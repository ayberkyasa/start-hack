"""T19: provider contract, result normalization, and frozen fallback order."""

import asyncio
import json
import unittest

from pydantic import SecretStr

from app.models import ModelRequest, ProviderError, ProviderSelection, run_fallback
from app.models.provider import ModelResult, usage_record
from app.storage.records import ModelUsage


def _result(outcome, **kwargs) -> ModelResult:
    base = dict(provider_id="openai", model_id="gpt-4o", latency_ms=5)
    return ModelResult(outcome=outcome, **base, **kwargs)


class FallbackOrderTests(unittest.TestCase):
    def test_error_then_completed_returns_completed(self):
        """An error outcome moves on to the next frozen candidate."""
        calls = []
        primary = ProviderSelection(provider_id="openai", model_id="gpt-4o")
        fallback = ProviderSelection(provider_id="openai", model_id="gpt-4o-mini")
        request = ModelRequest(model_id="gpt-4o", user_prompt="hi")

        def factory(selection):
            calls.append(selection)
            if selection.model_id == "gpt-4o":
                return _Fake([_result("error", error_code="content_filter")])
            return _Fake([_result("completed", value={"ok": True})])

        result = asyncio.run(run_fallback(request, factory, primary=primary, fallbacks=(fallback,)))
        self.assertEqual(result.outcome, "completed")
        self.assertEqual([c.model_id for c in calls], ["gpt-4o", "gpt-4o-mini"])

    def test_refusal_is_final_never_tries_fallback(self):
        """A refusal is a real answer and must not be retried on another model."""
        calls = []
        primary = ProviderSelection(provider_id="openai", model_id="gpt-4o")
        fallback = ProviderSelection(provider_id="openai", model_id="gpt-4o-mini")
        request = ModelRequest(model_id="gpt-4o", user_prompt="hi")

        def factory(selection):
            calls.append(selection)
            return _Fake([_result("refused", refusal_reason="policy")])

        result = asyncio.run(run_fallback(request, factory, primary=primary, fallbacks=(fallback,)))
        self.assertEqual(result.outcome, "refused")
        self.assertEqual(len(calls), 1)

    def test_all_errors_raise_provider_error_with_attempts(self):
        primary = ProviderSelection(provider_id="openai", model_id="gpt-4o")
        request = ModelRequest(model_id="gpt-4o", user_prompt="hi")

        def factory(selection):
            return _Fake([_result("error", error_code="server")])

        with self.assertRaises(ProviderError) as ctx:
            asyncio.run(run_fallback(request, factory, primary=primary))
        self.assertEqual(len(ctx.exception.attempts), 1)

    def test_usage_record_preserves_unknown_cost(self):
        """Unknown cost is not zero: estimated_usd_micros stays None."""
        result = _result("completed", value="x", input_tokens=10, output_tokens=4,
                         estimated_usd_micros=None, pricing_version=None)
        record = usage_record(usage_id="u1", run_id="r1",
                              recorded_at="2026-11-21T09:00:00Z", result=result)
        self.assertIsInstance(record, ModelUsage)
        self.assertIsNone(record.estimated_usd_micros)
        self.assertIsNone(record.pricing_version)
        self.assertEqual(record.outcome, "completed")

    def test_failures_do_not_mutate_a_submitted_action_payload(self):
        """The request is immutable; a failed provider cannot alter it."""
        request = ModelRequest(model_id="gpt-4o", user_prompt="secret-body")
        before = request.model_dump_json()
        with self.assertRaises(ProviderError):
            asyncio.run(run_fallback(
                request,
                lambda s: _Fake([_result("error", error_code="server")]),
                primary=ProviderSelection(provider_id="openai", model_id="gpt-4o"),
            ))
        # The call raised, and the request object is unchanged.
        self.assertEqual(request.model_dump_json(), before)


class _Fake:
    """Minimal adapter for tests; no network, no async runner dependency."""

    def __init__(self, results: list[ModelResult]) -> None:
        self._results = results

    async def complete(self, request: ModelRequest) -> ModelResult:
        return self._results.pop(0)