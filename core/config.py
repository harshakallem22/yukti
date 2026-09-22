"""Process configuration, loaded once from the environment.

Secrets live here and nowhere else — they must never reach AgentState, tool
arguments, prompts, or a subprocess environment.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=REPO_ROOT / ".env", extra="ignore", populate_by_name=True
    )

    # --- Model provider ---
    provider: Literal["openai", "fake"] = Field("openai", alias="YUKTI_MODEL_PROVIDER")
    openai_api_key: str = Field("", alias="OPENAI_API_KEY")
    investigator_model: str = Field("gpt-4.1", alias="YUKTI_INVESTIGATOR_MODEL")
    reviewer_model: str = Field("gpt-4.1", alias="YUKTI_REVIEWER_MODEL")
    model_timeout_seconds: int = Field(120, alias="YUKTI_MODEL_TIMEOUT_SECONDS")
    model_max_retries: int = Field(3, alias="YUKTI_MODEL_MAX_RETRIES")

    # --- Storage ---
    # SQLite by default so the stack runs with no external service; Postgres is
    # opt-in via docker compose. See ADR 002 amendment.
    database_url: str = Field(f"sqlite:///{REPO_ROOT}/yukti.db", alias="DATABASE_URL")

    # --- Sandbox ---
    sandbox_mode: Literal["local", "docker"] = Field("local", alias="YUKTI_SANDBOX_MODE")
    workspace_root: Path = Field(REPO_ROOT / "workspaces", alias="YUKTI_WORKSPACE_ROOT")
    command_timeout_seconds: int = Field(120, alias="YUKTI_COMMAND_TIMEOUT_SECONDS")
    max_output_bytes: int = Field(262_144, alias="YUKTI_MAX_OUTPUT_BYTES")

    # --- Agent budgets ---
    max_steps: int = Field(40, alias="YUKTI_MAX_STEPS")
    max_tool_calls: int = Field(60, alias="YUKTI_MAX_TOOL_CALLS")
    max_revisions: int = Field(3, alias="YUKTI_MAX_REVISIONS")
    max_tokens: int = Field(400_000, alias="YUKTI_MAX_TOKENS")
    max_wallclock_seconds: int = Field(900, alias="YUKTI_MAX_WALLCLOCK_SECONDS")

    # --- API ---
    api_host: str = Field("127.0.0.1", alias="YUKTI_API_HOST")
    api_port: int = Field(8010, alias="YUKTI_API_PORT")
    cors_origins: str = Field("http://localhost:5173", alias="YUKTI_CORS_ORIGINS")

    @field_validator("cors_origins")
    @classmethod
    def _reject_wildcard_origin(cls, v: str) -> str:
        # A wildcard origin on an API that executes code is not a default worth
        # allowing to pass silently.
        if "*" in v:
            raise ValueError("YUKTI_CORS_ORIGINS must list exact origins, not '*'")
        return v

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def has_model_access(self) -> bool:
        return self.provider == "fake" or bool(self.openai_api_key)


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
