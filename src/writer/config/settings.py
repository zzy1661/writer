from functools import lru_cache
from pathlib import Path

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


def load_env_file(path: Path | None) -> bool:
    """Load ``.env`` from ``path`` (file or directory) without overriding existing env.

    Returns ``True`` when a file was found and loaded.
    """

    if path is None:
        return False
    env_path = path if path.name == ".env" else path / ".env"
    if not env_path.is_file():
        return False
    from dotenv import load_dotenv

    load_dotenv(env_path, override=False)
    return True


def load_writer_config(path: Path | None) -> bool:
    """Load ``.writer/config`` from a project root with highest priority.

    The file uses the same ``WRITER_*`` key format as ``.env``. Values
    loaded here override any previously loaded environment variables.
    """

    if path is None:
        return False
    config_path = path / ".writer" / "config"
    if not config_path.is_file():
        return False
    from dotenv import load_dotenv

    load_dotenv(config_path, override=True)
    return True


def load_project_settings(project_root: Path | None) -> None:
    """Load project-level env files in priority order (low → high)."""

    if project_root is None:
        return
    load_env_file(project_root)
    load_writer_config(project_root)


def refresh_settings() -> Settings:
    """Clear the settings cache and rebuild from the current environment."""

    get_settings.cache_clear()
    return get_settings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
