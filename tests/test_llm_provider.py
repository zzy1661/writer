"""Unit tests for the LLM provider factory."""

from __future__ import annotations

from pydantic import SecretStr

from writer.config import Settings
from writer.llm import LLMConfigError, get_llm


def _settings(
    *,
    api_key: str | None = "sk-test",
    base_url: str = "https://api.openai.com/v1",
    model: str = "gpt-4o-mini",
    temperature: float = 0.5,
) -> Settings:
    return Settings(
        model=model,
        api_key=SecretStr(api_key) if api_key is not None else None,
        base_url=base_url,
        temperature=temperature,
    )


def test_get_llm_returns_chat_openai_with_settings_applied() -> None:
    settings = _settings(api_key="sk-abc", model="gpt-4o", temperature=0.3)

    llm = get_llm(settings)

    # ChatOpenAI stores the API key + base URL on these attributes
    assert llm.model_name == "gpt-4o"
    assert llm.openai_api_base == "https://api.openai.com/v1"
    assert llm.temperature == 0.3
    assert llm.openai_api_key is not None
    # The key may be stored as SecretStr by langchain-openai; only the
    # "not None / non-empty" guarantee is observable here.


def test_get_llm_missing_api_key_raises() -> None:
    settings = _settings(api_key=None)

    try:
        get_llm(settings)
    except LLMConfigError as exc:
        assert "WRITER_API_KEY" in str(exc)
    else:
        msg = "expected LLMConfigError when api_key is None"
        raise AssertionError(msg)


def test_get_llm_base_url_honored_for_openai_compatible_apis() -> None:
    settings = _settings(
        api_key="sk-deepseek",
        base_url="https://api.deepseek.com/v1",
        model="deepseek-chat",
    )

    llm = get_llm(settings)

    assert llm.openai_api_base == "https://api.deepseek.com/v1"
    assert llm.model_name == "deepseek-chat"


def test_llm_package_public_surface() -> None:
    """`from writer.llm import get_llm, LLMConfigError` must work."""

    # Re-import to make sure the re-exports are wired
    from writer.llm import LLMConfigError as _Err
    from writer.llm import get_llm as _get

    assert _get is get_llm
    assert _Err is LLMConfigError
