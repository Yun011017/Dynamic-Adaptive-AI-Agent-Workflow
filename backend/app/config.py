from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str
    migration_database_url: str = ""
    platform_api_key: str = ""
    platform_workspace_slug: str = "development"
    db_pool_mode: Literal["null", "queue"] = "null"
    db_connect_timeout: int = Field(default=10, ge=1, le=30)
    agent_provider: Literal["local", "gemini", "openai", "claude"] = "local"
    agent_model: str = "deterministic-langgraph"
    agent_worker_poll_seconds: int = Field(default=2, ge=1, le=60)
    agent_run_lease_seconds: int = Field(default=300, ge=30, le=3600)
    frontend_origins: str = "http://127.0.0.1:3000,http://localhost:3000"
    google_api_key: SecretStr | None = None
    openai_api_key: SecretStr | None = None
    anthropic_api_key: SecretStr | None = None
    google_forms_apps_script_url: str = ""
    google_forms_source_id: str = "connection-test"
    google_forms_member_column: str = "是否是社員"
    google_forms_attendance_column: str = "是否要參加"
    google_forms_event_date_column: str = "活動日期"
    google_forms_submitted_at_column: str = "時間戳記"
    google_forms_date_utc_offset_hours: int = Field(default=8, ge=-12, le=14)

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

