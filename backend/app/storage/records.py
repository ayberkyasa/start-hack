"""Additional persisted records for provenance, session notes, and metering."""

from typing import Self

from pydantic import AwareDatetime, model_validator

from app.domain.observations import Count
from app.settings import FrozenModel, Identifier


class EvidenceSource(FrozenModel):
    source_id: Identifier
    uri: str
    retrieved_at: AwareDatetime
    excerpt: str


class MemoryEntry(FrozenModel):
    entry_id: Identifier
    session_id: Identifier
    recorded_at: AwareDatetime
    text: str
    source_id: Identifier | None = None


class ModelUsage(FrozenModel):
    usage_id: Identifier
    run_id: Identifier
    recorded_at: AwareDatetime
    provider_id: Identifier
    model_id: Identifier
    input_tokens: Count | None = None
    output_tokens: Count | None = None
    duration_ms: Count
    estimated_usd_micros: Count | None = None
    pricing_version: Identifier | None = None
    error_code: Identifier | None = None

    @model_validator(mode="after")
    def check_estimate(self) -> Self:
        if self.estimated_usd_micros is not None and self.pricing_version is None:
            raise ValueError("A cost estimate requires a pricing version")
        return self
