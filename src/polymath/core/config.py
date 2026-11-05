"""Application settings, loaded from environment variables (prefix ``POLYMATH_``) and ``.env``.

Provider API keys (``ANTHROPIC_API_KEY``, ``OPENAI_API_KEY``, ...) are *not* modelled here:
LiteLLM reads them from the process environment, which :func:`load_env_file` populates.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from polymath.core.models import AgentRole, RunBudget

DEFAULT_ROLE_MODELS: dict[AgentRole, str] = {
    AgentRole.SUPERVISOR: "claude-opus-5-5",
    AgentRole.REASONER: "claude-opus-5-5",
    AgentRole.FORMALIZER: "claude-opus-5-5",
    AgentRole.CRITIC: "claude-sonnet-5-5",
    AgentRole.COMPUTE: "claude-sonnet-5-5",
    AgentRole.LITERATURE: "claude-sonnet-5-5",
    AgentRole.SYNTHESIZER: "claude-sonnet-5-5",
}


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

    # LLM gateway
    role_models: dict[AgentRole, str] = Field(default_factory=lambda: dict(DEFAULT_ROLE_MODELS))
    fallback_models: list[str] = Field(default_factory=lambda: ["gpt-5", "gemini/gemini-2.5-pro"])
    degraded_model: str = "claude-haiku-5-5"
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

    # Docker images for tool servers
    sandbox_image: str = "polymath-sandbox:latest"
    lean_image: str = "polymath-lean:v4.35.0"

    # Default budget for a run
    budget: RunBudget = Field(default_factory=RunBudget)

    # Tracing (OTLP/HTTP; Langfuse ingests this from Phase 6)
    otel_exporter_endpoint: str | None = None
    otel_service_name: str = "polymath"
    otel_console: bool = False

    def model_for(self, role: AgentRole) -> str:
        return self.role_models.get(role, DEFAULT_ROLE_MODELS[role])


def load_env_file(path: Path | None = None) -> None:
    """Load ``.env`` into ``os.environ`` (without overriding real env vars) for provider SDKs."""
    load_dotenv(dotenv_path=path or Path(".env"), override=False)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
