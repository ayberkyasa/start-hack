"""Offline client for the fixed library exchange, for transcript and UI consumers."""

import json
from copy import deepcopy
from pathlib import Path
from typing import Protocol

from pydantic import Field, JsonValue

from app.domain.records import Observation
from app.settings import FrozenModel, Identifier


FIXTURES = Path(__file__).resolve().parents[3] / "fixtures"


class Exchange(FrozenModel):
    step_id: Identifier
    operation: Identifier
    request: dict[str, JsonValue]
    body: dict[str, JsonValue] | None
    request_key: Identifier | None = None
    error_status: int | None = Field(default=None, ge=400, le=599)
    repeat_of: Identifier | None = None


class ReplayClient(Protocol):
    """Consumer interface for selecting and reading recorded mock exchanges."""

    def scenarios(self) -> list[dict[str, JsonValue]]: ...
    def channels(self) -> tuple[str, ...]: ...
    def steps(self) -> tuple[str, ...]: ...
    def advance(self, step_id: str) -> Exchange: ...
    def session(self) -> dict[str, JsonValue] | None: ...
    def events(self) -> list[dict[str, JsonValue]]: ...


class LibraryReplay:
    def __init__(self):
        script = json.loads((FIXTURES / "target/library.json").read_text())
        transcript = json.loads((FIXTURES / "domain/transcript.json").read_text())
        self._scenario = script["scenario"]
        self._channels = tuple(script["channels"])
        responses = {}
        for record in transcript["history"]:
            if record["kind"] == "observation":
                observation = Observation.model_validate(record)
                # Validate the typed portion and keep unknown wire fields for inspection.
                responses[observation.record_id] = record["content"]["response"]

        self._steps: dict[str, Exchange] = {}
        for step in script["steps"]:
            step_id = step["id"]
            if step_id in self._steps:
                raise ValueError(f"Duplicate fixture step: {step_id}")
            if "repeat_of" in step:
                original = self._steps[step["repeat_of"]]
                exchange = original.model_copy(update={"step_id": step_id, "repeat_of": original.step_id})
            else:
                body = responses[step["observation_id"]] if "observation_id" in step else step["body"]
                exchange = Exchange(
                    step_id=step_id, operation=step["operation"], request=step["request"],
                    body=body, error_status=step.get("error_status"), request_key=step.get("request_key"),
                )
            self._steps[step_id] = exchange

        self._order = tuple(self._steps)
        self._position = 0
        self._session: dict[str, JsonValue] | None = None
        self._events: list[dict[str, JsonValue]] = []

    def scenarios(self) -> list[dict[str, JsonValue]]:
        return [deepcopy(self._scenario)]

    def channels(self) -> tuple[str, ...]:
        return self._channels

    def steps(self) -> tuple[str, ...]:
        return self._order

    def session(self) -> dict[str, JsonValue] | None:
        return deepcopy(self._session)

    def events(self) -> list[dict[str, JsonValue]]:
        return deepcopy(self._events)

    def advance(self, step_id: str) -> Exchange:
        """Read a completed step again or consume the next step in recording order."""
        exchange = self._steps[step_id]
        index = self._order.index(step_id)
        if index > self._position:
            raise ValueError(f"Next fixture step is {self._order[self._position]}")
        if index == self._position:
            if exchange.repeat_of is None and exchange.error_status is None:
                self._apply(exchange)
            self._position += 1
        return exchange.model_copy(deep=True)

    def _apply(self, exchange: Exchange) -> None:
        body = exchange.body
        if exchange.operation == "session.open":
            if body is None:
                raise ValueError("Fixture session requires an opening receipt")
            self._session = body.copy()
        elif self._session is None:
            raise ValueError("Fixture session must be opened first")
        elif exchange.operation == "session.close":
            self._session["status"] = "ended"
        elif isinstance(body, dict):
            if "touches_used" in body:
                self._session["touches_used"] = body["touches_used"]
            events = body.get("events", [])
            if not isinstance(events, list) or not all(isinstance(event, dict) for event in events):
                raise ValueError("Fixture events must be a list of objects")
            self._events.extend(events)
