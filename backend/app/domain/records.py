"""Typed records for inspecting one run and the history associated with it."""

from enum import StrEnum
from typing import Annotated, Literal, Self

from pydantic import AwareDatetime, Field, StrictBool, model_validator

from app.domain.observations import Count, ObservationContent
from app.settings import FrozenModel, Identifier, RunSnapshot


class RunPhase(StrEnum):
    PREPARING = "preparing"
    RESEARCHING = "researching"
    READY = "ready"
    PLANNING = "planning"
    VALIDATING = "validating"
    EXECUTING = "executing"
    OBSERVING = "observing"
    RECOVERING = "recovering"
    STOPPING = "stopping"
    FINISHED = "finished"


class TerminalReason(StrEnum):
    OBJECTIVE_EVIDENCE_OBTAINED = "objective_evidence_obtained"
    BUDGET_EXHAUSTED = "budget_exhausted"
    NO_USEFUL_CONTINUATION = "no_useful_continuation"
    EXECUTION_BLOCKED = "execution_blocked"
    OPERATOR_ABORTED = "operator_aborted"


class Run(FrozenModel):
    run_id: Identifier
    configuration: RunSnapshot
    phase: RunPhase
    terminal_reason: TerminalReason | None = None
    created_at: AwareDatetime

    @model_validator(mode="after")
    def finished_has_reason(self) -> Self:
        if self.phase == RunPhase.FINISHED and self.terminal_reason is None:
            raise ValueError("a finished run requires a terminal reason")
        return self


class Session(FrozenModel):
    run_id: Identifier
    session_id: Identifier
    scenario_id: Identifier
    status: Identifier
    touch_budget: Count
    touches_used: Count


class ActionStatus(StrEnum):
    PREPARED = "prepared"
    IN_FLIGHT = "in_flight"
    OUTCOME_UNKNOWN = "outcome_unknown"
    SUCCEEDED = "succeeded"
    REJECTED = "rejected"
    CANCELLED_BEFORE_SEND = "cancelled_before_send"


class Action(FrozenModel):
    action_id: Identifier
    run_id: Identifier
    operation: Identifier
    status: ActionStatus
    request_body_ref: Identifier
    session_id: Identifier | None = None
    conversation_id: Identifier | None = None
    target_id: Identifier | None = None
    channel: Identifier | None = None
    artifact_version_ids: tuple[Identifier, ...] = ()


class Attempt(FrozenModel):
    attempt_id: Identifier
    action_id: Identifier
    started_at: AwareDatetime
    finished_at: AwareDatetime | None = None
    http_status: Annotated[int, Field(strict=True, ge=100, le=599)] | None = None
    redacted_response_ref: Identifier | None = None


class Conversation(FrozenModel):
    conversation_id: Identifier
    session_id: Identifier
    target_id: Identifier
    channel: Identifier
    greeting_observation_id: Identifier
    turns_used: Annotated[int, Field(strict=True, ge=0, le=10)]
    ended: StrictBool


class ArtifactVersion(FrozenModel):
    artifact_id: Identifier
    version_id: Identifier
    kind: Literal["message", "page", "attachment", "asset"]
    content_ref: Identifier
    created_at: AwareDatetime


class HistoryRecord(FrozenModel):
    record_id: Identifier
    run_id: Identifier
    action_id: Identifier | None = None
    recorded_at: AwareDatetime


class Observation(HistoryRecord):
    kind: Literal["observation"]
    content: ObservationContent


class Decision(HistoryRecord):
    kind: Literal["decision"]
    summary: str
    evidence_ids: tuple[Identifier, ...]


class Assessment(HistoryRecord):
    kind: Literal["assessment"]
    summary: str
    evidence_ids: Annotated[tuple[Identifier, ...], Field(min_length=1)]


HistoryEntry = Annotated[Observation | Decision | Assessment, Field(discriminator="kind")]
