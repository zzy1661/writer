"""Tests for provider-compatible structured LLM output helpers."""

from __future__ import annotations

from langchain_core.messages import AIMessage
from pydantic import BaseModel

from writer.config import Settings
from writer.llm.structured import (
    invoke_structured_json,
    needs_json_prompt_structured_output,
)


class _Payload(BaseModel):
    name: str
    count: int


class _FakeChat:
    def __init__(self, content: str) -> None:
        self.content = content

    def invoke(self, messages: object) -> AIMessage:
        self.messages = messages
        return AIMessage(content=self.content)


def test_needs_json_prompt_structured_output_detects_deepseek() -> None:
    settings = Settings(model="deepseek-v4-pro", base_url="https://api.deepseek.com")

    assert needs_json_prompt_structured_output(settings)


def test_needs_json_prompt_structured_output_keeps_openai_native_path() -> None:
    settings = Settings(model="gpt-4o-mini", base_url="https://api.openai.com/v1")

    assert not needs_json_prompt_structured_output(settings)


def test_invoke_structured_json_parses_plain_json() -> None:
    fake = _FakeChat('{"name": "大纲", "count": 4}')

    result = invoke_structured_json(fake, [], _Payload)  # type: ignore[arg-type]

    assert result == _Payload(name="大纲", count=4)


def test_invoke_structured_json_extracts_json_from_markdown_fence() -> None:
    fake = _FakeChat(
        """
        ```json
        {"name": "路由", "count": 1}
        ```
        """
    )

    result = invoke_structured_json(fake, [], _Payload)  # type: ignore[arg-type]

    assert result.name == "路由"
    assert result.count == 1
