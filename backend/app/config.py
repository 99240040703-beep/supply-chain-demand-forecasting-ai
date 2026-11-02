from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    database_url: str = "sqlite:///./supply_chain.db"
    secret_key: str = "CHANGE_ME"
    access_token_minutes: int = 1440
    cors_origins: str = "http://localhost:5173"
    openai_api_key: str | None = None
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

settings = Settings()
