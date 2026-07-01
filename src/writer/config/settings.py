from functools import lru_cache

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Runtime settings loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="WRITER_",
        extra="ignore",
    )

    model: str = "gpt-4o-mini"
    api_key: SecretStr | None = None
    base_url: str = "https://api.openai.com/v1"
    temperature: float = Field(default=0.7, ge=0.0, le=2.0)

    @property
    def has_api_key(self) -> bool:
        return self.api_key is not None and bool(self.api_key.get_secret_value())


@lru_cache
def get_settings() -> Settings:
    return Settings()
