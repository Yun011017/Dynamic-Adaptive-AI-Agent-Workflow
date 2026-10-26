from pathlib import Path
from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    migration_database_url: str = ""
    platform_api_key: str = ""
    platform_workspace_slug: str = "development"
    db_pool_mode: Literal["null", "queue"] = "null"
    db_connect_timeout: int = Field(default=10, ge=1, le=30)
    agent_provider: Literal["local"] = "local"
    agent_model: str = "deterministic-langgraph"

    model_config = SettingsConfigDict(
        env_file=Path(__file__).resolve().parents[1] / ".env",
        extra="ignore",
    )

    @field_validator("database_url", "migration_database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        value = value.strip()
        if not value:
            return value
        for prefix in ("postgresql://", "postgres://"):
            if value.startswith(prefix):
                return "postgresql+psycopg://" + value[len(prefix):]
        return value


settings = Settings()

