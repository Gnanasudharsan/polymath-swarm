"""Application settings, loaded from environment variables (prefix ``POLYMATH_``) and ``.env``.

Provider API keys (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ...) are *not* modelled here:
LiteLLM reads them from the process environment, which :func:`load_env_file` populates.
"""

from __future__ import annotations

import os
from functools import lru_cache
from pathlib import Path
from typing import Literal, Self

from dotenv import load_dotenv
from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from polymath.core.models import AgentRole, RunBudget

ModelProfileName = Literal["anthropic", "openai"]


class ModelProfile(BaseModel):
    """A coherent set of model choices for one provider."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role_models: dict[AgentRole, str]
    fallback_models: list[str]
    degraded_model: str
    reasoning_effort: str | None = None


MODEL_PROFILES: dict[ModelProfileName, ModelProfile] = {
    # Default per ADR-0001: Claude primary, other providers as fallbacks.
    "anthropic": ModelProfile(
        role_models={
            AgentRole.SUPERVISOR: "claude-opus-5-5",
            AgentRole.REASONER: "claude-opus-5-5",
            AgentRole.FORMALIZER: "claude-opus-5-5",
            AgentRole.CRITIC: "claude-sonnet-5-5",
            AgentRole.COMPUTE: "claude-sonnet-5-5",
            AgentRole.LITERATURE: "claude-sonnet-5-5",
            AgentRole.SYNTHESIZER: "claude-sonnet-5-5",
        },
        fallback_models=["gpt-5", "gemini/gemini-2.5-pro"],
        degraded_model="claude-haiku-5-5",
    ),
    # OpenAI-only deployments: the stronger model where proofs need it, mini elsewhere.
    "openai": ModelProfile(
        role_models={
            AgentRole.SUPERVISOR: "gpt-5-mini",
            AgentRole.REASONER: "gpt-5-mini",
            AgentRole.FORMALIZER: "gpt-5",
            AgentRole.CRITIC: "gpt-5-mini",
            AgentRole.COMPUTE: "gpt-5-mini",
            AgentRole.LITERATURE: "gpt-5-mini",
            AgentRole.SYNTHESIZER: "gpt-5-mini",
        },
        fallback_models=["gpt-5-nano"],
        degraded_model="gpt-5-nano",
        reasoning_effort="low",
    ),
}
DEFAULT_ROLE_MODELS: dict[AgentRole, str] = dict(MODEL_PROFILES["anthropic"].role_models)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="POLYMATH_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["dev", "test", "prod"] = "dev"
    log_level: str = "INFO"
    log_json: bool = False

    # Datastores
    postgres_dsn: str = "postgresql://polymath:polymath@localhost:5544/polymath"
    redis_url: str = "redis://localhost:6379/0"

    # LLM gateway. Fields left unset are filled from `model_profile`.
    model_profile: ModelProfileName = "anthropic"
    role_models: dict[AgentRole, str] = Field(default_factory=lambda: dict(DEFAULT_ROLE_MODELS))
    fallback_models: list[str] = Field(default_factory=lambda: ["gpt-5", "gemini/gemini-2.5-pro"])
    degraded_model: str = "claude-haiku-5-5"
    reasoning_effort: str | None = None
    degrade_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    llm_timeout_s: float = Field(default=120.0, gt=0)
    llm_max_retries: int = Field(default=3, ge=0)
    llm_retry_base_delay_s: float = Field(default=1.0, ge=0)
    llm_max_output_tokens: int = Field(default=8192, gt=0)

    # Literature APIs (unprefixed env names, matching each provider's docs)
    semantic_scholar_api_key: SecretStr | None = Field(
        default=None, validation_alias="SEMANTIC_SCHOLAR_API_KEY"
    )
    openalex_mailto: str | None = Field(default=None, validation_alias="OPENALEX_MAILTO")
    openalex_api_key: SecretStr | None = Field(default=None, validation_alias="OPENALEX_API_KEY")
    literature_cache_ttl_s: int = Field(default=86_400, gt=0)

    # Memory & knowledge (local ONNX models via fastembed; downloaded once to the cache dir)
    embedding_model: str = "BAAI/bge-small-en-v1.5"
    embedding_dim: int = 384
    rerank_model: str | None = "Xenova/ms-marco-MiniLM-L-6-v2"
    model_cache_dir: Path = Field(default_factory=lambda: Path.home() / ".cache" / "polymath")
    memory_enabled: bool = True
    memory_min_similarity: float = Field(default=0.80, ge=0.0, le=1.0)

    # Docker images for tool servers
    sandbox_image: str = "polymath-sandbox:latest"
    lean_image: str = "polymath-lean:v4.35.0"

    # Cross-run spend ledger (optional hard cap on cumulative LLM spend)
    spend_ledger: Path | None = None
    spend_cap_usd: float | None = Field(default=None, gt=0)

    # Default budget for a run
    budget: RunBudget = Field(default_factory=RunBudget)

    # Tracing (OTLP/HTTP; Langfuse ingests this from Phase 6)
    otel_exporter_endpoint: str | None = None
    otel_service_name: str = "polymath"
    otel_console: bool = False

    @model_validator(mode="after")
    def _apply_profile(self) -> Self:
        profile = MODEL_PROFILES[self.model_profile]
        explicit = self.model_fields_set
        if "role_models" not in explicit:
            self.role_models = dict(profile.role_models)
        if "fallback_models" not in explicit:
            self.fallback_models = list(profile.fallback_models)
        if "degraded_model" not in explicit:
            self.degraded_model = profile.degraded_model
        if "reasoning_effort" not in explicit:
            self.reasoning_effort = profile.reasoning_effort
        return self

    def model_for(self, role: AgentRole) -> str:
        return self.role_models.get(role, DEFAULT_ROLE_MODELS[role])


def load_env_file(path: Path | None = None) -> None:
    """Load ``.env`` into ``os.environ`` (without overriding real env vars) for provider SDKs.

    Set ``POLYMATH_NO_DOTENV=1`` to skip it (the test suite does, so local settings such as the
    spend ledger never leak into tests).
    """
    if os.environ.get("POLYMATH_NO_DOTENV") == "1":
        return
    load_dotenv(dotenv_path=path or Path(".env"), override=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    if os.environ.get("POLYMATH_NO_DOTENV") == "1":
        return Settings(_env_file=None)
    return Settings()
