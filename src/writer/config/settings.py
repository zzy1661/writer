from functools import lru_cache
from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """从环境变量加载的运行时配置。"""

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
    """从 ``path``（文件或目录）加载 ``.env``，不覆盖现有环境变量。

    找到并加载文件时返回 ``True``。
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
    """从项目根加载 ``.writer/config``，优先级最高。

    该文件使用与 ``.env`` 相同的 ``WRITER_*`` 键格式。这里加载的
    值覆盖任何先前加载的环境变量。
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
    """按优先级（低 → 高）加载项目级 env 文件。"""

    if project_root is None:
        return
    load_env_file(project_root)
    load_writer_config(project_root)


def refresh_settings() -> Settings:
    """清空 settings 缓存并从当前环境重建。"""

    get_settings.cache_clear()
    return get_settings()


@lru_cache
def get_settings() -> Settings:
    return Settings()
