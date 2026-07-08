"""全局 pytest 配置:测试期间禁止加载 .env,避免误用真实 API key。

工作原理:
- pydantic-settings v2 中,``Settings(_env_file=None)`` 会完全跳过 .env 读取。
- ``Settings.__init__`` 在测试期间被 monkeypatch 注入 ``_env_file=None``。
- ``get_settings()`` 的 ``lru_cache`` 在每个测试前后清空,避免缓存值带 .env。
- ``autouse=True`` 自动应用于所有测试。

注意:某些测试(如 ``test_cli.py::test_repl_handles_help_and_user_input``)
会通过 :func:`writer.config.load_env_file` 间接调用 ``dotenv.load_dotenv``,
把 ``WRITER_API_KEY`` 写进 ``os.environ``。``Settings._env_file=None`` 拦不住
这条路径(pydantic-settings 仍会读 OS env),所以 fixture 在 teardown 阶段
主动清理 ``WRITER_*`` 残留,防止污染后续测试。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

_WRITER_ENV_VARS = (
    "WRITER_API_KEY",
    "WRITER_MODEL",
    "WRITER_BASE_URL",
    "WRITER_TEMPERATURE",
)


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

    # Teardown: defensively scrub any WRITER_* vars that a test may have
    # leaked into ``os.environ`` via ``load_env_file`` /
    # ``dotenv.load_dotenv``. Without this, downstream ``Settings()`` calls
    # would pick up an API key even though ``_env_file=None`` was set.
    for var in _WRITER_ENV_VARS:
        os.environ.pop(var, None)
