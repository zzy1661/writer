"""LLM provider 工厂。

从 :class:`writer.config.Settings` 构建 LangChain ``ChatOpenAI``。
工厂是代码库中唯一实例化 LLM 的地方，因此替换 provider（Anthropic、
本地 vLLM、Azure OpenAI）只需改一个文件。

通过 ``Settings.base_url`` 支持 OpenAI 兼容端点（DeepSeek、Moonshot 等）；
``ChatOpenAI`` 直接遵守该字段。
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from writer.config import Settings


class LLMConfigError(ValueError):
    """``Settings`` 缺少构建 LLM 所需的值时抛出。"""


def get_llm(settings: Settings) -> ChatOpenAI:
    """从 ``settings`` 实例化 ``ChatOpenAI``。

    Raises:
        LLMConfigError: 若 ``settings.has_api_key`` 为 False。
    """

    if not settings.has_api_key:
        msg = (
            "无法构造 LLM:缺少 API Key。请在 .env 中设置 WRITER_API_KEY "
            "(或在调用前注入 settings.api_key)。"
        )
        raise LLMConfigError(msg)

    api_key = settings.api_key.get_secret_value()  # type: ignore[union-attr]
    return ChatOpenAI(
        model=settings.model,
        temperature=settings.temperature,
        api_key=SecretStr(api_key),
        base_url=settings.base_url,
    )


__all__ = ["LLMConfigError", "get_llm"]
