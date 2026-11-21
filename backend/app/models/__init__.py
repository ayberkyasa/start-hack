"""Model-provider adapters.

A provider factory turns a frozen provider/model selection into a concrete
adapter. The internal contract (:class:`ModelProvider`) keeps application state
independent of any vendor conversation object.
"""

from __future__ import annotations

from pydantic import SecretStr

from app.models.openai_adapter import OpenAIProvider
from app.models.provider import (
    MockProvider,
    ModelProvider,
    ModelRequest,
    ModelResult,
    ProviderError,
    ProviderSelection,
    run_fallback,
    usage_record,
)

__all__ = [
    "MockProvider",
    "ModelProvider",
    "ModelRequest",
    "ModelResult",
    "OpenAIProvider",
    "ProviderError",
    "ProviderSelection",
    "run_fallback",
    "usage_record",
]


def provider_for(
    selection: ProviderSelection,
    *,
    openai_api_key: SecretStr | None,
    request_timeout_seconds: int,
    retries: int,
) -> ModelProvider:
    """Build one adapter for a frozen selection, without network side effects."""
    if selection.provider_id == "mock":
        return MockProvider(selection.model_id)
    if selection.provider_id == "openai":
        if openai_api_key is None:
            raise ValueError("OPENAI_API_KEY is required for the openai provider")
        return OpenAIProvider(
            openai_api_key,
            model_id=selection.model_id,
            timeout_seconds=request_timeout_seconds,
            max_retries=retries,
        )
    raise ValueError(f"Unknown provider id: {selection.provider_id}")
