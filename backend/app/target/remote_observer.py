"""Read scenario availability and inspect existing Target API session history."""

import asyncio
import json
from contextlib import closing
from http.client import HTTPException, HTTPSConnection
from urllib.parse import quote

from pydantic import SecretStr, TypeAdapter

from app.settings import Identifier, Settings
from app.storage.timeline import redact
from app.target.observer import EventHistory, ReadError, ReadFailure, ScenarioAvailability, SessionView


_HOST = "target-api.apps.01.cf.eu01.stackit.cloud"
_SCENARIOS = TypeAdapter(tuple[ScenarioAvailability, ...])
_CHANNELS = TypeAdapter(tuple[Identifier, ...])
_SESSIONS = TypeAdapter(tuple[SessionView, ...])
_SESSION = TypeAdapter(SessionView)
_HISTORY = TypeAdapter(EventHistory)
_STATUS = {
    401: ReadFailure.AUTHENTICATION,
    403: ReadFailure.FORBIDDEN,
    404: ReadFailure.NOT_FOUND,
    429: ReadFailure.RATE_LIMIT,
}


def _session_path(session_id: str) -> str:
    if (not session_id or session_id in (".", "..") or "/" in session_id
            or "\\" in session_id or any(ord(char) < 32 for char in session_id)):
        raise ValueError("Invalid session ID")
    return "/sessions/" + quote(session_id, safe="")


class RemoteObserver:
    def __init__(self, team_key: SecretStr, *, timeout_seconds: int, extra_secrets: tuple[SecretStr, ...] = ()):
        token = team_key.get_secret_value()
        if not token or not token.isascii() or not token.isprintable() or any(c.isspace() for c in token):
            raise ValueError("The team key must be a nonempty HTTP token")
        if not 1 <= timeout_seconds <= 600:
            raise ValueError("Read timeout must be between 1 and 600 seconds")
        self._team_key = team_key
        self._timeout = timeout_seconds
        self._secrets = (team_key, *extra_secrets)

    @classmethod
    def from_settings(cls, settings: Settings):
        if settings.run.mode == "mock" or settings.target_api_team_key is None:
            raise ValueError("Remote reads require practice or eval settings")
        extras = (settings.openai_api_key,) if settings.openai_api_key else ()
        return cls(settings.target_api_team_key, timeout_seconds=settings.run.limits.request_timeout_seconds,
                   extra_secrets=extras)

    def _get(self, path: str) -> bytes:
        headers = {"Authorization": "Bearer " + self._team_key.get_secret_value(), "Accept": "application/json"}
        try:
            with closing(HTTPSConnection(_HOST, timeout=self._timeout)) as connection:
                connection.request("GET", "/v1" + path, headers=headers)
                with connection.getresponse() as response:
                    if response.status != 200:
                        default = ReadFailure.UNAVAILABLE if response.status >= 500 else ReadFailure.REJECTED
                        raise ReadError(_STATUS.get(response.status, default), response.status)
                    return response.read()
        except TimeoutError:
            raise ReadError(ReadFailure.TIMEOUT) from None
        except (OSError, HTTPException):
            raise ReadError(ReadFailure.TRANSPORT) from None

    async def _read[T](self, path: str, schema: TypeAdapter[T]) -> T:
        raw = await asyncio.to_thread(self._get, path)
        try:
            value = redact(json.loads(raw), self._secrets)
            return schema.validate_python(value)
        except (ValueError, RecursionError):
            raise ReadError(ReadFailure.BAD_RESPONSE) from None

    async def scenarios(self) -> tuple[ScenarioAvailability, ...]:
        return await self._read("/scenarios", _SCENARIOS)

    async def channels(self) -> tuple[str, ...]:
        return await self._read("/channels", _CHANNELS)

    async def sessions(self) -> tuple[SessionView, ...]:
        return await self._read("/sessions", _SESSIONS)

    async def session(self, session_id: str) -> SessionView:
        session = await self._read(_session_path(session_id), _SESSION)
        if session.session_id != session_id:
            raise ReadError(ReadFailure.BAD_RESPONSE)
        return session

    async def history(self, session_id: str) -> EventHistory:
        return await self._read(_session_path(session_id) + "/events", _HISTORY)
