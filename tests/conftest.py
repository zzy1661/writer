"""全局 pytest 配置:测试期间禁止加载 .env,避免误用真实 API key。

工作原理:
- pydantic-settings v2 中,``Settings(_env_file=None)`` 会完全跳过 .env 读取。
- ``Settings.__init__`` 在测试期间被 monkeypatch 注入 ``_env_file=None``。
- ``get_settings()`` 的 ``lru_cache`` 在每个测试前后清空,避免缓存值带 .env。
- ``autouse=True`` 自动应用于所有测试。
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _disable_dotenv_loading(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """强制 ``Settings()`` 走 ``_env_file=None``,屏蔽 .env 加载。"""

    from writer.config import settings as settings_mod
    from writer.config.settings import Settings

    settings_mod.get_settings.cache_clear()

    original_init = Settings.__init__

    def init_without_env_file(self, **kwargs: object) -> None:
        kwargs.setdefault("_env_file", None)
        original_init(self, **kwargs)

    monkeypatch.setattr(Settings, "__init__", init_without_env_file)
    yield
    settings_mod.get_settings.cache_clear()