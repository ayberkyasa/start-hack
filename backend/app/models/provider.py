"""Internal model-provider contract.

Application state must not depend on a vendor conversation object (SPEC 9).
Adapters normalize structured success, refusal, incomplete output, provider
errors, and usage into the types here. A cost estimate is never guessed:
an unknown price stays ``None`` and is distinct from a confirmed zero cost.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol, runtime_checkable

from pydantic import AwareDatetime

from app.settings import FrozenModel, Identifier, ProviderSelection
from app.storage.records import ModelUsage


# Reuse the recorded outcome vocabulary so usage rows and provider results agree.
ModelOutcome = Literal["completed", "refused", "incomplete", "error"]


class ModelRequest(FrozenModel):
    """Structured, vendor-neutral completion request."""

    model_id: Identifier
    system_prompt: str = ""
    user_prompt: str = ""
    max_output_tokens: int = 1024
    temperature: float = 0.0
    # A JSON schema (plain dict) that the provider must satisfy. Absent means
    # free text; present requests strict structured output.
    response_schema: dict | None = None
    request_id: Identifier | None = None


class ModelResult(FrozenModel):
    """Normalized outcome of one provider call."""

    outcome: ModelOutcome
    # Structured output parsed from the provider response, or free text when no
    # schema was requested. None on refusal, incomplete, or error.
    value: str | dict | None = None
    refusal_reason: str | None = None
    error_code: Identifier | None = None
    provider_id: Identifier
    model_id: Identifier
    input_tokens: int | None = None
    output_tokens: int | None = None
    latency_ms: int | None = None
    # Estimated cost in USD millionths. None means the price is unknown, not zero.
    estimated_usd_micros: int | None = None
    pricing_version: Identifier | None = None


class ProviderError(RuntimeError):
    """Raised when no configured provider/model can satisfy a request."""

    def __init__(self, message: str, *, attempts: tuple[ModelResult, ...]) -> None:
        super().__init__(message)
        self.attempts = attempts


@runtime_checkable
class ModelProvider(Protocol):
    """A provider returns one normalized result; it never raises for a model call."""

    async def complete(self, request: ModelRequest) -> ModelResult: ...


async def run_fallback(
    request: ModelRequest,
    providers: Callable[[ProviderSelection], ModelProvider],
    *,
    primary: ProviderSelection,
    fallbacks: tuple[ProviderSelection, ...] = (),
) -> ModelResult:
    """Try the primary then each fallback in frozen order and return the first result.

    Providers are constructed lazily per selection so a missing credential or a
    broken adapter does not stop the primary path. All attempts are returned in
    the exception so callers can record them and never hide the failure reason.
    """
    order = (primary, *fallbacks)
    attempts: list[ModelResult] = []
    for selection in order:
        provider = providers(selection)
        try:
            result = await provider.complete(request)
        except Exception as error:  # adapter contract: always returns a result
            raise ProviderError(
                f"provider {selection.provider_id}/{selection.model_id} raised: {error!r}",
                attempts=tuple(attempts),
            ) from error
        attempts.append(result)
        if result.outcome in ("completed", "refused", "incomplete"):
            # Refusal and incomplete are real, final answers, not transport retries.
            return result
        # error outcomes are retryable only on another provider/model candidate.
    raise ProviderError("no provider returned a usable result", attempts=tuple(attempts))


def usage_record(
    *,
    usage_id: str,
    run_id: str,
    recorded_at: AwareDatetime,
    result: ModelResult,
) -> ModelUsage:
    """Convert a normalized result into a durable ModelUsage row."""
    return ModelUsage(
        usage_id=usage_id,
        run_id=run_id,
        recorded_at=recorded_at,
        provider_id=result.provider_id,
        model_id=result.model_id,
        outcome=result.outcome,
        input_tokens=result.input_tokens,
        output_tokens=result.output_tokens,
        duration_ms=result.latency_ms if result.latency_ms is not None else 0,
        estimated_usd_micros=result.estimated_usd_micros,
        pricing_version=result.pricing_version,
        error_code=result.error_code,
    )


class MockProvider:
    """Deterministic, offline provider for mock runs and deterministic tests.

    For a structured request it returns a fixed object so no network or model is
    needed. This keeps mock runs reproducible and never touches real credentials.
    """

    def __init__(self, model_id: str) -> None:
        self._model_id = model_id

    async def complete(self, request: ModelRequest) -> ModelResult:
        return ModelResult(
            outcome="completed",
            value={"plan": "scripted", "model": self._model_id} if request.response_schema else "scripted",
            provider_id="mock",
            model_id=request.model_id or self._model_id,
            input_tokens=0,
            output_tokens=0,
            latency_ms=0,
            estimated_usd_micros=0,
            pricing_version="mock-free",
        )