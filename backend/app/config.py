from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://agent:agent_dev_password@db:5432/agent_workflow"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()

