"""LLM provider factory.

Builds a LangChain ``ChatOpenAI`` from :class:`writer.config.Settings`. The
factory is the only place in the codebase that instantiates an LLM, so
swapping providers (Anthropic, local vLLM, Azure OpenAI) is a one-file
change.

OpenAI-compatible endpoints (DeepSeek, Moonshot, etc.) are supported via
``Settings.base_url``; ``ChatOpenAI`` honors that field directly.
"""

from __future__ import annotations

from langchain_openai import ChatOpenAI
from pydantic import SecretStr

from writer.config import Settings


class LLMConfigError(ValueError):
    """Raised when ``Settings`` lacks the values needed to build an LLM."""


def get_llm(settings: Settings) -> ChatOpenAI:
    """Instantiate ``ChatOpenAI`` from ``settings``.

    Raises:
        LLMConfigError: if ``settings.has_api_key`` is False.
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
