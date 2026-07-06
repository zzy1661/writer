"""Provider-compatible structured LLM output helpers.

Some OpenAI-compatible providers (notably DeepSeek at the time this
module was added) reject the ``response_format`` payload emitted by
LangChain's native structured-output path. This helper keeps the same
Pydantic boundary while asking the model for plain JSON and validating
the result locally.
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage, SystemMessage
from pydantic import BaseModel, ValidationError

from writer.config import Settings

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class StructuredOutputError(ValueError):
    """Raised when a JSON-prompt structured LLM response cannot be validated."""


def needs_json_prompt_structured_output(settings: Settings) -> bool:
    """Return True for providers that should avoid native ``response_format``.

    The check is intentionally configuration-based rather than model-class
    based: OpenAI-compatible providers all use ``ChatOpenAI`` locally, so
    the base URL / model name are the stable signals available at runtime.
    """

    marker = f"{settings.base_url} {settings.model}".lower()
    return "deepseek" in marker


def invoke_structured_json[ModelT: BaseModel](
    llm: BaseChatModel,
    messages: Sequence[BaseMessage],
    schema: type[ModelT],
) -> ModelT:
    """Invoke ``llm`` and parse a Pydantic model from a plain JSON response."""

    response = llm.invoke([_json_contract_message(schema), *messages])
    text = _message_content_to_text(response.content)
    payload = _extract_json_object(text)
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        msg = f"LLM JSON 未通过 {schema.__name__} 校验: {exc}"
        raise StructuredOutputError(msg) from exc


def _json_contract_message(schema: type[BaseModel]) -> SystemMessage:
    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return SystemMessage(
        content=(
            "你必须只输出一个合法 JSON 对象，不要输出 Markdown、解释、代码围栏或额外文本。\n"
            f"JSON 必须符合这个 Pydantic schema: {schema_json}"
        )
    )


def _message_content_to_text(content: object) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        return "\n".join(parts)
    return str(content)


def _extract_json_object(text: str) -> object:
    fenced = _JSON_FENCE_RE.search(text)
    candidate = fenced.group(1).strip() if fenced else text.strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(candidate):
        if char != "{":
            continue
        try:
            obj, _end = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        return obj

    msg = "LLM 响应中未找到合法 JSON 对象"
    raise StructuredOutputError(msg)


__all__ = [
    "StructuredOutputError",
    "invoke_structured_json",
    "needs_json_prompt_structured_output",
]
