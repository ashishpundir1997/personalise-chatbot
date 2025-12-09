import os
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Global configuration for environment variables."""
    
    APP_NAME: str = "Neo Chat Wrapper"
    ENV: str = os.getenv("ENV", "development")

    # Server config
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", 8080))

    # API Keys
    OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
    ANTHROPIC_API_KEY: str | None = os.getenv("ANTHROPIC_API_KEY")
    GEMINI_API_KEY: str | None = os.getenv("GEMINI_API_KEY")
    GEMINI_FREE_ENDPOINT: str | None = os.getenv("GEMINI_FREE_ENDPOINT")
    OLLAMA_BASE_URL: str | None = os.getenv("OLLAMA_BASE_URL")
    DEEPSEEK_API_KEY: str | None = os.getenv("DEEPSEEK_API_KEY")
    DEEPSEEK_BASE_URL: str | None = os.getenv("DEEPSEEK_BASE_URL")

    # Internal microservice
    PY_SERVICE_URL: str = os.getenv("PY_SERVICE_URL", "http://localhost:9090")

    # Debug
    DEBUG: bool = os.getenv("DEBUG", "True").lower() in ("1", "true")

    ROUTING_STRATEGY: str = os.getenv("ROUTING_STRATEGY", "primary") # Options: "primary", "hedge", "fastest"
    REQUEST_TIMEOUT_MS: int = int(os.getenv("REQUEST_TIMEOUT_MS", "15000"))
    HEDGE_DELAY_MS: int = int(os.getenv("HEDGE_DELAY_MS", "250"))
    # End of new fields

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="allow")


settings = Settings()
