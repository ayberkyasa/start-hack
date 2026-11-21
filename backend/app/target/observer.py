"""Read-only views for the console and its offline fixture."""

from enum import StrEnum
from typing import Protocol

from pydantic import StrictBool, TypeAdapter

from app.domain.observations import Count, ObservedEvent, RemoteData
from app.settings import Identifier
from app.target.replay import LibraryReplay


class ScenarioAvailability(RemoteData):
    id: Identifier
    kind: Identifier | None = None
    open: StrictBool | None = None
    opens_at: str | None = None


class SessionView(RemoteData):
    session_id: Identifier
    scenario_id: Identifier
    status: Identifier
    touch_budget: Count
    touches_used: Count


class EventHistory(RemoteData):
    events: tuple[ObservedEvent, ...]


class ReadFailure(StrEnum):
    AUTHENTICATION = "authentication"
    FORBIDDEN = "forbidden"
    NOT_FOUND = "not_found"
    RATE_LIMIT = "rate_limit"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    TRANSPORT = "transport"
    BAD_RESPONSE = "bad_response"
    REJECTED = "rejected"


class ReadError(Exception):
    def __init__(self, kind: ReadFailure, status: int | None = None):
        self.kind = kind
        self.status = status
        super().__init__(kind.value if status is None else f"{kind.value} (HTTP {status})")


class Observer(Protocol):
    async def scenarios(self) -> tuple[ScenarioAvailability, ...]: ...
    async def channels(self) -> tuple[str, ...]: ...
    async def sessions(self) -> tuple[SessionView, ...]: ...
    async def session(self, session_id: str) -> SessionView: ...
    async def history(self, session_id: str) -> EventHistory: ...


class LibraryObserver:
    """Observe playback at its current cursor. Reading never advances the script."""

    def __init__(self, replay: LibraryReplay):
        self._replay = replay

    async def scenarios(self) -> tuple[ScenarioAvailability, ...]:
        return TypeAdapter(tuple[ScenarioAvailability, ...]).validate_python(self._replay.scenarios())

    async def channels(self) -> tuple[str, ...]:
        return self._replay.channels()

    async def sessions(self) -> tuple[SessionView, ...]:
        state = self._replay.session()
        return () if state is None else (SessionView.model_validate(state),)

    async def session(self, session_id: str) -> SessionView:
        sessions = await self.sessions()
        if sessions and sessions[0].session_id == session_id:
            return sessions[0]
        raise ReadError(ReadFailure.NOT_FOUND, 404)

    async def history(self, session_id: str) -> EventHistory:
        await self.session(session_id)
        return EventHistory.model_validate({"events": self._replay.events()})
