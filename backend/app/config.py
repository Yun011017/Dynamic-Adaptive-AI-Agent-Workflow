from pathlib import Path
from typing import Literal

from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Meta Instagram 發布設定
    meta_ig_user_id: str = ""
    meta_access_token: SecretStr | None = None
    graph_api_version: str = "v21.0"
    
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
    # Cloudflare R2 uses its S3-compatible API. Keep credentials server-side;
    # the browser only ever receives the public URL returned after upload.
    r2_account_id: str = ""
    r2_access_key_id: str = ""
    r2_secret_access_key: SecretStr | None = None
    r2_bucket_name: str = ""
    r2_public_base_url: str = ""
    # Direct browser-to-R2 uploads are not constrained by Vercel request bodies.
    # Keep an application-level cap below the S3 POST 5 GiB object limit.
    r2_max_upload_bytes: int = Field(default=100 * 1024 * 1024, ge=1, le=5 * 1024 * 1024 * 1024)
    # A small fallback avoids a browser CORS outage blocking ordinary images.
    # Larger files must use the direct R2 path and never cross Vercel.
    r2_proxy_fallback_max_bytes: int = Field(default=4 * 1024 * 1024, ge=1, le=20 * 1024 * 1024)
    media_upload_ttl_hours: int = Field(default=24, ge=1, le=168)
    cron_secret: SecretStr | None = None
    google_forms_apps_script_url: str = ""
    google_forms_source_id: str = "connection-test"
    google_forms_member_column: str = "是否是社員"
    google_forms_attendance_column: str = "是否要參加"
    google_forms_school_column: str = "學校"
    google_forms_department_grade_column: str = "系級"
    google_forms_activity_column: str = "參加的活動"
    google_forms_submitted_at_column: str = "時間戳記"
    google_forms_email_column: str = "電子郵件地址"
    google_forms_name_column: str = "姓名"
    google_forms_source_column: str = "文案來源"
    # Explicit mapping for this experiment; never infer an execution from its order.
    google_forms_execution_map: dict[str, int] = {}
    # Empty means timezone-less timestamps remain invalid.
    google_forms_naive_timezone: str = ""

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

    @property
    def r2_enabled(self) -> bool:
        return bool(
            self.r2_account_id
            and self.r2_access_key_id
            and self.r2_secret_access_key
            and self.r2_bucket_name
            and self.r2_public_base_url
        )

    @property
    def r2_endpoint_url(self) -> str:
        return f"https://{self.r2_account_id}.r2.cloudflarestorage.com"


settings = Settings()

