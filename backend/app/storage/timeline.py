"""Read models and credential filtering for saved timeline data."""

import re

from typing import Literal

from pydantic import AwareDatetime, Field, JsonValue, SecretStr

from app.settings import FrozenModel, Identifier


class TimelineEntry(FrozenModel):
    sequence: int
    run_id: Identifier
    record_id: Identifier
    action_id: Identifier | None
    recorded_at: AwareDatetime
    origin: Literal["observation", "assessment", "decision", "remote"]
    kind: str
    payload: dict[str, JsonValue]


class RawResponse(FrozenModel):
    attempt_id: Identifier
    body: JsonValue = Field(repr=False)


# Ignore casing and punctuation in transport/header names. Counts such as
# input_tokens are useful diagnostics and carry no credential.
_PRIVATE = {
    "headers", "requestheaders", "responseheaders", "authorization", "proxyauthorization",
    "cookie", "setcookie", "password", "passwd", "secret", "token", "credentials",
}
_SUFFIXES = ("apikey", "teamkey", "accesstoken", "refreshtoken", "clientsecret",
             "password", "authtoken", "idtoken", "apitoken", "privatekey", "secretkey")
_AUTH_VALUE = re.compile(r"\b(Bearer|Basic)\s+[A-Za-z0-9+/=._~-]+", re.IGNORECASE)


def _private(name: str) -> bool:
    key = re.sub(r"[^a-z0-9]", "", name.lower())
    return key in _PRIVATE or key.endswith(_SUFFIXES)


def redact(value: JsonValue, secrets: tuple[SecretStr, ...]) -> JsonValue:
    if isinstance(value, dict):
        if any(isinstance(value.get(k), str) and _private(value[k]) for k in ("name", "key")):
            return {"redacted": True}
        result = {}
        for key, item in value.items():
            if _private(key):
                continue
            if key == "fields":
                if isinstance(item, list) and all(isinstance(x, str) for x in item):
                    result[key] = [redact(name, secrets) for name in item]
                continue
            result[redact(key, secrets)] = redact(item, secrets)
        return result
    if isinstance(value, list):
        if len(value) == 2 and isinstance(value[0], str) and _private(value[0]):
            return ["[REDACTED]"]
        return [redact(item, secrets) for item in value]
    if isinstance(value, str):
        for secret in secrets:
            literal = secret.get_secret_value()
            if literal:
                value = value.replace(literal, "[REDACTED]")
        return _AUTH_VALUE.sub(r"\1 [REDACTED]", value)
    return value
