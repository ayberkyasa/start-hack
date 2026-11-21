"""Client for the revel8 Target API (Road to START Hack 2026).

A thin, faithful wrapper over every endpoint documented in API_DOCS.md. It owns the
cross-cutting concerns the docs call out so callers don't have to:

- Bearer auth with the team key.
- Long timeouts: every request runs a language model, "allow up to 90 seconds".
- Retries on the transient codes the docs say to retry (429/502/503/504), with backoff
  that honours `Retry-After`; 400/422 are raised immediately ("change it, do not retry").
- Idempotency-Key on every message, conversation start and turn, generated once per
  contact and reused across that contact's retries so a timeout never double-spends a touch.
- Typed errors (`Revel8APIError`) carrying the status code and the server message.

Methods return the parsed JSON (dicts/lists) exactly as the API shapes it, so the docs
are the reference for every field. `from` is a Python keyword, so sender info is passed
as `sender=` and serialised to the `"from"` field.

Example:
    api = APIClient(team_key=os.environ["TARGET_API_TEAM_KEY"])
    sid = api.create_session("practice")["session_id"]
    r = api.send_message(sid, to="julius", channel="email",
                         sender={"name": "Lena Hofer", "address": "lena.hofer@eventcrew-muc.de"},
                         subject="Speaker logistics", body="Hi Julius, ...")
    if not r["events"]:
        ...  # ignored: follow up, switch channel, or stop
"""
from __future__ import annotations

import time
import uuid
from typing import Any, Iterable, Mapping, Optional, Sequence, Union

import requests

BASE_URL = "https://target-api.apps.01.cf.eu01.stackit.cloud/v1"

# Transient codes the docs tell us to wait and retry; everything else is final.
RETRY_STATUS = {429, 502, 503, 504}
# Documented request limits, enforced client-side so a bad call fails fast and locally
# instead of spending a round-trip to a 413/422.
MAX_SAY_CHARS = 4000
MAX_ATTACHMENTS_MESSAGE = 10
MAX_ATTACHMENTS_TURN = 5
MAX_PAGE_FIELDS = 20


class Revel8APIError(Exception):
    """An API response the client could not treat as success.

    `status` is the HTTP code; `payload` is the parsed error body when there was one.
    `retryable` marks the transient codes, in case a caller wants to back off further."""

    def __init__(self, status: int, message: str, payload: Any = None):
        super().__init__(f"{status}: {message}")
        self.status = status
        self.message = message
        self.payload = payload
        self.retryable = status in RETRY_STATUS


class APIClient:
    """One instance per team key. Safe to reuse across sessions and threads-of-work; it
    keeps a single `requests.Session` for connection reuse. It does NOT parallelise: the
    docs cap concurrency (6 per team, 4 queued per session), so drive it one call at a time
    per session and wait for each response."""

    def __init__(
        self,
        team_key: str,
        base_url: str = BASE_URL,
        timeout: float = 120.0,
        max_retries: int = 3,
        backoff: float = 3.0,
        min_interval: float = 0.0,
    ):
        if not team_key:
            raise ValueError("team_key is required")
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self.backoff = backoff
        self.min_interval = min_interval  # optional client-side spacing to stay under 60 rpm
        self._last_request_at = 0.0
        self._session = requests.Session()
        self._session.headers["Authorization"] = f"Bearer {team_key}"

    # -- internals ---------------------------------------------------------------

    def _throttle(self) -> None:
        if self.min_interval <= 0:
            return
        wait = self._last_request_at + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        files: Any = None,
        idempotency_key: Optional[str] = None,
        timeout: Optional[float] = None,
    ) -> Any:
        """Send one request with retry on transient failures.

        The same `idempotency_key` is sent on every attempt of a given contact, so a retry
        after a timeout returns the original response and spends no second touch. 400/422
        are final (the same body fails again); 401/403/404/409/413/415 are raised as-is."""
        url = f"{self.base_url}{path}"
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        last_exc: Optional[Exception] = None

        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self._session.request(
                    method, url, json=json, files=files, headers=headers,
                    timeout=timeout or self.timeout,
                )
            except requests.RequestException as exc:
                # Connection reset / read timeout: safe to retry because the idempotency key
                # (or the docs' 2-minute same-body window) protects against a double touch.
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(self.backoff * (attempt + 1))
                    continue
                raise Revel8APIError(0, f"request failed: {exc}") from exc
            finally:
                self._last_request_at = time.monotonic()

            if resp.status_code in RETRY_STATUS and attempt < self.max_retries - 1:
                time.sleep(self._retry_after(resp, attempt))
                continue

            if resp.ok:
                return self._json_or_none(resp)

            raise Revel8APIError(resp.status_code, self._error_message(resp),
                                 self._json_or_none(resp))

        # Exhausted retries on a transient code.
        raise Revel8APIError(getattr(last_exc, "status", 0) or 0,
                             f"gave up after {self.max_retries} attempts")

    def _retry_after(self, resp: requests.Response, attempt: int) -> float:
        header = resp.headers.get("Retry-After")
        if header:
            try:
                return float(header)
            except ValueError:
                pass
        return self.backoff * (attempt + 1)

    @staticmethod
    def _json_or_none(resp: requests.Response) -> Any:
        if not resp.content:
            return None
        try:
            return resp.json()
        except ValueError:
            return None

    @staticmethod
    def _error_message(resp: requests.Response) -> str:
        body = APIClient._json_or_none(resp)
        if isinstance(body, Mapping):
            for key in ("message", "detail", "error"):
                if body.get(key):
                    return str(body[key])
        return (resp.text or resp.reason or "").strip()[:500]

    @staticmethod
    def _message_payload(
        to: str,
        channel: str,
        sender: Optional[Mapping[str, Any]],
        subject: Optional[str],
        body: str,
        attachments: Optional[Sequence[Any]],
        sent_at: Optional[Union[str, int, float]],
    ) -> dict:
        payload: dict[str, Any] = {"to": to, "channel": channel, "body": body}
        if sender:
            payload["from"] = dict(sender)
        if subject:
            payload["subject"] = subject
        if attachments:
            if len(attachments) > MAX_ATTACHMENTS_MESSAGE:
                raise ValueError(f"at most {MAX_ATTACHMENTS_MESSAGE} attachments per message")
            payload["attachments"] = list(attachments)
        if sent_at is not None:
            payload["sent_at"] = sent_at
        return payload

    # -- scenarios & channels ----------------------------------------------------

    def list_scenarios(self) -> list:
        """`GET /scenarios` — every scenario (practice + eval). Eval shows only id/opens_at
        until the scoring window opens."""
        return self._request("GET", "/scenarios")

    def get_scenario(self, scenario_id: str) -> Optional[dict]:
        """Convenience: the one scenario with this id, or None. (The API only lists.)"""
        for s in self.list_scenarios():
            if s.get("id") == scenario_id:
                return s
        return None

    def list_channels(self) -> Any:
        """`GET /channels` — the current channel list (may change during the event)."""
        return self._request("GET", "/channels")

    # -- sessions ----------------------------------------------------------------

    def create_session(self, scenario_id: str) -> dict:
        """`POST /sessions` — open a session (one continuous exchange). Returns session_id,
        touch_budget, touches_used, status, story_time. An eval session counts as a run only
        once a touch is used; reopening an unused one returns the same session."""
        return self._request("POST", "/sessions", json={"scenario_id": scenario_id})

    def get_session(self, session_id: str) -> dict:
        """`GET /sessions/{id}` — current state, including `story_time` (the session clock)."""
        return self._request("GET", f"/sessions/{session_id}")

    def list_sessions(self) -> list:
        """`GET /sessions` — all your sessions, newest first (resume after a crash)."""
        return self._request("GET", "/sessions")

    def get_events(self, session_id: str) -> list:
        """`GET /sessions/{id}/events` — every event so far. Unwraps the `{"events": [...]}`."""
        data = self._request("GET", f"/sessions/{session_id}/events")
        return data.get("events", []) if isinstance(data, Mapping) else (data or [])

    def end_session(self, session_id: str) -> Any:
        """`POST /sessions/{id}/end` — end the session."""
        return self._request("POST", f"/sessions/{session_id}/end")

    # -- assets ------------------------------------------------------------------

    def upload_asset(self, file: Any, filename: Optional[str] = None,
                     content_type: Optional[str] = None) -> dict:
        """`POST /assets` — upload an image (PNG/JPG/WebP) or PDF, up to 5 MB. `file` is a
        path or an open binary file object. Returns {asset_id, type, size}. Reference the
        id inline with `<img src="asset://a_1">` or list it in `attachments`."""
        close = False
        if isinstance(file, (str, bytes)) and not hasattr(file, "read"):
            fh = open(file, "rb")
            close = True
            filename = filename or (file if isinstance(file, str) else "upload")
        else:
            fh = file
        try:
            part = (filename, fh, content_type) if (filename or content_type) else fh
            return self._request("POST", "/assets", files={"file": part})
        finally:
            if close:
                fh.close()

    # -- landing pages -----------------------------------------------------------

    def register_page(
        self,
        session_id: str,
        url: str,
        *,
        title: Optional[str] = None,
        html: Optional[str] = None,
        text: Optional[str] = None,
        images: Optional[Sequence[str]] = None,
        fields: Optional[Sequence[str]] = None,
    ) -> dict:
        """`POST /sessions/{id}/pages` — register the URL you will link to and what is behind
        it. Provide `html` (self-contained, no scripts, images only from your assets) OR
        `text` (+ optional `images`) for a plain form. Name `fields` as the form labels them;
        the field name decides what a submission counts as (secret/internal/basic). Registering
        the same URL again in the same session replaces the page. Returns {page_id}."""
        if fields and len(fields) > MAX_PAGE_FIELDS:
            raise ValueError(f"at most {MAX_PAGE_FIELDS} fields per page")
        payload: dict[str, Any] = {"url": url}
        if title:
            payload["title"] = title
        if html:
            payload["html"] = html
        if text:
            payload["text"] = text
        if images:
            payload["images"] = list(images)
        if fields:
            payload["fields"] = list(fields)
        return self._request("POST", f"/sessions/{session_id}/pages", json=payload)

    # -- messages ----------------------------------------------------------------

    def send_message(
        self,
        session_id: str,
        to: str,
        channel: str,
        *,
        body: str,
        sender: Optional[Mapping[str, Any]] = None,
        subject: Optional[str] = None,
        attachments: Optional[Sequence[Any]] = None,
        sent_at: Optional[Union[str, int, float]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """`POST /sessions/{id}/messages` — one message; the response is the reaction.
        Returns {message_id, touches_used, events}. `events == []` means it was ignored.

        `sender` is the visible `from` (name + address/number/handle); every field is a
        claim. `attachments` may mix uploaded asset ids with declared files
        ({"filename","transcript"} for audio, {"filename"} for anything else). `sent_at`
        is the story time (ISO-8601 or epoch), forward-only within a session.

        A fresh idempotency key is generated per call and reused on its retries, so a timeout
        cannot spend a second touch. Pass your own key to tie several attempts together."""
        payload = self._message_payload(to, channel, sender, subject, body, attachments, sent_at)
        key = idempotency_key or str(uuid.uuid4())
        return self._request("POST", f"/sessions/{session_id}/messages",
                             json=payload, idempotency_key=key)

    # -- conversations (live channels) ------------------------------------------

    def start_conversation(
        self,
        session_id: str,
        to: str,
        channel: str,
        *,
        sender: Optional[Mapping[str, Any]] = None,
        sent_at: Optional[Union[str, int, float]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """`POST /sessions/{id}/conversations` — ring a live channel (phone_call, video_call,
        teams_call, live_chat). The person always picks up. Returns {conversation_id, status,
        persona_says, touches_used}. Costs one touch; a conversation allows at most 10 turns."""
        payload: dict[str, Any] = {"to": to, "channel": channel}
        if sender:
            payload["from"] = dict(sender)
        if sent_at is not None:
            payload["sent_at"] = sent_at
        key = idempotency_key or str(uuid.uuid4())
        return self._request("POST", f"/sessions/{session_id}/conversations",
                             json=payload, idempotency_key=key)

    def say(
        self,
        conversation_id: str,
        text: str,
        *,
        attachments: Optional[Sequence[Any]] = None,
        sent_at: Optional[Union[str, int, float]] = None,
        idempotency_key: Optional[str] = None,
    ) -> dict:
        """`POST /conversations/{id}/turns` — say one line. Returns {persona_says, ended,
        events, turns_used}. `ended` is True when they hang up; `events` carries anything
        they did during the turn (e.g. opening a link you dictated), keyed by conversation_id.
        `attachments` (max 5) may show/share something mid-call."""
        if len(text) > MAX_SAY_CHARS:
            raise ValueError(f"`say` is limited to {MAX_SAY_CHARS} characters")
        payload: dict[str, Any] = {"say": text}
        if attachments:
            if len(attachments) > MAX_ATTACHMENTS_TURN:
                raise ValueError(f"at most {MAX_ATTACHMENTS_TURN} attachments per turn")
            payload["attachments"] = list(attachments)
        if sent_at is not None:
            payload["sent_at"] = sent_at
        key = idempotency_key or str(uuid.uuid4())
        return self._request("POST", f"/conversations/{conversation_id}/turns",
                             json=payload, idempotency_key=key)

    def end_conversation(self, conversation_id: str) -> Any:
        """`POST /conversations/{id}/end` — hang up. Starting another conversation with the
        same person also ends the one still open."""
        return self._request("POST", f"/conversations/{conversation_id}/end")


if __name__ == "__main__":
    # Smoke check: list scenarios and channels with the team key from the environment.
    import json as _json
    import os

    client = APIClient(team_key=os.environ["TARGET_API_TEAM_KEY"])
    print("scenarios:", _json.dumps(client.list_scenarios(), indent=2))
    print("channels:", _json.dumps(client.list_channels(), indent=2))
