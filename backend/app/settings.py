"""Server settings and the public, reproducible inputs to a run."""

import hashlib
import json
import os
from collections.abc import Mapping
from typing import Annotated, Literal, Self

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    SecretStr,
    StringConstraints,
    ValidationError,
    model_validator,
)


class FrozenModel(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", hide_input_in_errors=True)


Identifier = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=256)
]


class RunLimits(FrozenModel):
    """Integral units avoid rounding differences in the snapshot."""

    model_config = ConfigDict(strict=True)

    contacts: int = Field(default=10, ge=1, le=30)
    turns_per_call: int = Field(default=10, ge=1, le=10)
    wall_seconds: int = Field(default=1800, ge=1, le=86_400)
    request_timeout_seconds: int = Field(default=120, ge=1, le=600)
    research_requests: int = Field(default=8, ge=0, le=1000)
    model_calls: int = Field(default=32, ge=0, le=1000)
    model_tokens: int = Field(default=64_000, ge=0, le=10_000_000)
    estimated_spend_usd_cents: int = Field(default=100, ge=0, le=100_000)
    idle_planner_iterations: int = Field(default=4, ge=1, le=100)
    repairs: int = Field(default=2, ge=0, le=10)
    retries: int = Field(default=2, ge=0, le=10)


class RunConfig(FrozenModel):
    mode: Literal["mock", "practice", "eval"]
    provider_id: Literal["mock", "openai"]
    model_id: Identifier
    limits: RunLimits

    @model_validator(mode="after")
    def check_mode(self) -> Self:
        if (self.mode == "mock") != (self.provider_id == "mock"):
            raise ValueError("APP_PROVIDER_ID must match APP_MODE (mock or live)")
        if self.mode == "eval" and self.limits.contacts > 10:
            raise ValueError("APP_RUN_LIMITS.contacts exceeds the eval maximum of 10")
        return self


class RunSnapshot(RunConfig):
    schema_version: Literal[1] = 1
    scenario_id: Identifier
    code_revision: Identifier

    def canonical_json(self) -> str:
        return json.dumps(self.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))

    def config_hash(self) -> str:
        return hashlib.sha256(self.canonical_json().encode("utf-8")).hexdigest()


class Settings(FrozenModel):
    run: RunConfig
    openai_api_key: SecretStr | None = Field(default=None, exclude=True, repr=False)
    target_api_team_key: SecretStr | None = Field(default=None, exclude=True, repr=False)

    @model_validator(mode="after")
    def require_live_credentials(self) -> Self:
        if self.run.mode != "mock":
            for name, value in (
                ("OPENAI_API_KEY", self.openai_api_key),
                ("TARGET_API_TEAM_KEY", self.target_api_team_key),
            ):
                if value is None or not value.get_secret_value().strip():
                    raise ValueError(f"{name} is required for practice and eval")
        return self

    def freeze(self, *, scenario_id: str, code_revision: str) -> RunSnapshot:
        return RunSnapshot(
            **self.run.model_dump(), scenario_id=scenario_id, code_revision=code_revision
        )


def load_settings(environ: Mapping[str, str] | None = None) -> Settings:
    env = os.environ if environ is None else environ
    mode = env.get("APP_MODE", "mock")
    provider = env.get("APP_PROVIDER_ID", "mock" if mode == "mock" else "openai")
    try:
        limits = RunLimits.model_validate_json(env.get("APP_RUN_LIMITS", "{}"))
    except ValidationError as error:
        # An unknown JSON key or a parse error can itself contain sensitive input.
        issues = []
        for detail in error.errors(include_input=False, include_url=False, include_context=False):
            field = next(iter(detail["loc"]), None)
            if field in RunLimits.model_fields:
                issues.append(f"{field}: {detail['msg']}")
            else:
                issues.append("expected a JSON object containing only known limit names")
        raise ValueError("Invalid APP_RUN_LIMITS: " + ", ".join(issues)) from None

    try:
        run = RunConfig.model_validate({
            "mode": mode,
            "provider_id": provider,
            "model_id": env.get("APP_MODEL_ID", "local-fixture" if mode == "mock" else ""),
            "limits": limits,
        })
        return Settings.model_validate({
            "run": run,
            "openai_api_key": env.get("OPENAI_API_KEY"),
            "target_api_team_key": env.get("TARGET_API_TEAM_KEY"),
        })
    except ValidationError as error:
        fields = {"mode": "APP_MODE", "provider_id": "APP_PROVIDER_ID", "model_id": "APP_MODEL_ID"}
        problems = []
        for detail in error.errors(include_input=False, include_url=False):
            label = fields.get(next(iter(detail["loc"]), None))
            message = detail["msg"]
            problems.append(f"{label}: {message}" if label else message)
        raise ValueError("Invalid server configuration: " + ", ".join(problems)) from None
