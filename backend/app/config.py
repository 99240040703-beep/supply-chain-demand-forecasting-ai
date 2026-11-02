from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Use a Render PostgreSQL internal URL in production. SQLite remains useful locally.
    database_url: str = "sqlite:///./supply_chain.db"
    secret_key: str = "CHANGE_ME"
    access_token_minutes: int = 1440
    cors_origins: str = "http://localhost:5173"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o-mini"
    openai_timeout_seconds: float = 35.0
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
