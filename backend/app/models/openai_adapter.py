"""OpenAI chat-completions adapter with strict structured output support.

Talks to ``POST https://api.openai.com/v1/chat/completions`` using the standard
library, matching the codebase's read-side adapter style. It normalizes the
vendor response into :class:`ModelResult` and never raises for a model call.

Verified against the current official contract (checked 2026-11-21):
- Endpoint ``/v1/chat/completions`` with ``Authorization: Bearer <key>``.
- Structured output: ``response_format={"type": "json_schema",
  "json_schema": {"name": ..., "schema": ..., "strict": true}}``.
- Response usage: ``usage.prompt_tokens``, ``usage.completion_tokens``,
  ``usage.total_tokens``; latency from the ``openai-processing-ms`` header.
- Refusal is signaled by ``message.refusal``; ``finish_reason`` of ``stop``,
  ``length``, or ``content_filter``.
- Errors are JSON ``{"error": {"code", "message", "type"}}``.
"""

from __future__ import annotations

import asyncio
import json
import time
from contextlib import closing
from http.client import HTTPException, HTTPSConnection
from typing import Literal

from pydantic import SecretStr

from app.models.provider import ModelRequest, ModelResult

_HOST = "api.openai.com"
_CHAT_PATH = "/v1/chat/completions"


class OpenAIError(RuntimeError):
    """A transport or server error that should be retried on another candidate."""


def _estimate_cost(input_tokens: int, output_tokens: int, model_id: str) -> tuple[int, str] | None:
    """Return ``(estimated_usd_micros, pricing_version)`` or ``None`` when unknown.

    A missing price is *unknown*, never zero, so callers can distinguish a free
    model from one whose price we could not confirm. Prices are snapshotted here
    per model family; any model without a listed rate returns ``None``.
    """
    rates = {
        # (input per 1M tokens, output per 1M tokens) in USD cents.
        "gpt-4.1": (200, 800),
        "gpt-4.1-mini": (40, 160),
        "gpt-4o": (250, 1000),
        "gpt-4o-mini": (15, 60),
    }
    # Match the most specific family first so gpt-4o-mini is not caught by gpt-4o.
    ordered = sorted(rates, key=len, reverse=True)
    for prefix in ordered:
        if model_id.startswith(prefix):
            input_cents, output_cents = rates[prefix]
            micros = input_tokens * input_cents * 10 + output_tokens * output_cents * 10
            return micros, "openai-2020-10-01"
    return None


class OpenAIProvider:
    """A single provider/model candidate backed by the OpenAI chat completions API."""

    def __init__(
        self,
        api_key: SecretStr,
        *,
        model_id: str,
        timeout_seconds: int,
        max_retries: int = 0,
    ) -> None:
        token = api_key.get_secret_value()
        if not token or not token.isascii() or not token.isprintable():
            raise ValueError("The OpenAI API key must be a nonempty HTTP token")
        if not 1 <= timeout_seconds <= 600:
            raise ValueError("OpenAI timeout must be between 1 and 600 seconds")
        if max_retries < 0:
            raise ValueError("max_retries must be nonnegative")
        self._api_key = api_key
        self._model_id = model_id
        self._timeout = timeout_seconds
        self._max_retries = max_retries

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": "Bearer " + self._api_key.get_secret_value(),
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _payload(self, request: ModelRequest) -> dict:
        messages = []
        if request.system_prompt:
            messages.append({"role": "system", "content": request.system_prompt})
        messages.append({"role": "user", "content": request.user_prompt})
        payload: dict = {
            "model": request.model_id,
            "messages": messages,
            "temperature": request.temperature,
            "max_completion_tokens": request.max_output_tokens,
        }
        if request.response_schema is not None:
            payload["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.request_id or "response",
                    "schema": request.response_schema,
                    "strict": True,
                },
            }
        return payload

    def _post(self, request: ModelRequest) -> dict:
        body = json.dumps(self._payload(request), separators=(",", ":")).encode("utf-8")
        last_error: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                return self._post_once(body)
            except OpenAIError:
                raise
            except (TimeoutError, OSError, HTTPException) as error:
                # Transient transport problems are retried up to the bound.
                last_error = error
                if attempt < self._max_retries:
                    time.sleep(0.2 * (2**attempt))
        raise OpenAIError(f"OpenAI transport failed after retries: {last_error!r}")

    def _post_once(self, body: bytes) -> dict:
        with closing(HTTPSConnection(_HOST, timeout=self._timeout)) as connection:
            connection.request("POST", _CHAT_PATH, body=body, headers=self._headers())
            with connection.getresponse() as response:
                processing_ms = response.getheader("openai-processing-ms")
                raw = response.read()
        if response.status != 200:
            try:
                parsed = json.loads(raw)
                code = parsed.get("error", {}).get("code") or "unknown"
                message = parsed.get("error", {}).get("message") or "OpenAI request failed"
            except (ValueError, AttributeError):
                code, message = "unknown", raw[:200].decode("utf-8", "replace")
            raise OpenAIError(f"OpenAI {response.status} {code}: {message}")
        try:
            parsed = json.loads(raw)
        except ValueError as error:
            raise OpenAIError(f"OpenAI returned non-JSON: {error!r}") from error
        parsed["_processing_ms"] = processing_ms
        return parsed

    async def complete(self, request: ModelRequest) -> ModelResult:
        started = time.monotonic()
        try:
            parsed = await asyncio.to_thread(self._post, request)
        except OpenAIError as error:
            return ModelResult(
                outcome="error",
                error_code="error",
                provider_id="openai",
                model_id=request.model_id,
                latency_ms=_elapsed_ms(started),
            )
        elapsed = _elapsed_ms(started)
        processing = _as_int(parsed.pop("_processing_ms", None))
        usage = parsed.get("usage") or {}
        input_tokens = _as_int(usage.get("prompt_tokens"))
        output_tokens = _as_int(usage.get("completion_tokens"))
        choice = (parsed.get("choices") or [{}])[0]
        message = choice.get("message") or {}
        refusal = message.get("refusal") or None
        finish = choice.get("finish_reason")
        content = message.get("content") or ""

        outcome: Literal["completed", "refused", "incomplete", "error"] = "completed"
        value: str | dict | None = None
        error_code = None
        if refusal:
            outcome, value, error_code = "refused", None, "refused"
        elif finish == "length":
            outcome, value, error_code = "incomplete", content, "length"
        elif finish == "content_filter":
            outcome, value, error_code = "error", None, "content_filter"
        else:
            if request.response_schema is not None:
                parsed_ok = True
                try:
                    value = json.loads(content)
                except ValueError:
                    outcome, error_code, parsed_ok = "incomplete", "not_json", False
                if parsed_ok and not isinstance(value, dict):
                    outcome, error_code = "incomplete", "not_object"
            else:
                value = content

        cost = None
        if input_tokens is not None and output_tokens is not None:
            cost = _estimate_cost(input_tokens, output_tokens, request.model_id)
        return ModelResult(
            outcome=outcome,
            value=value,
            refusal_reason=refusal,
            error_code=error_code,
            provider_id="openai",
            model_id=request.model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            latency_ms=processing if processing is not None else elapsed,
            estimated_usd_micros=cost[0] if cost else None,
            pricing_version=cost[1] if cost else None,
        )


def _elapsed_ms(started: float) -> int:
    return max(0, round((time.monotonic() - started) * 1000))


def _as_int(value: object) -> int | None:
    return value if isinstance(value, int) else None