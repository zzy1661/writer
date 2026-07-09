"""Provider 兼容的结构化 LLM 输出辅助函数。

一些 OpenAI 兼容 provider（尤其是添加本模块时的 DeepSeek）会拒绝
LangChain 原生结构化输出路径产出的 ``response_format`` payload。本
辅助函数保持同一 Pydantic 边界，但向模型请求纯 JSON 并在本地校验结果。
"""

from __future__ import annotations

import json
import re
from collections.abc import Sequence

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import BaseMessage
from pydantic import BaseModel, ValidationError

from writer.config import Settings
from writer.prompts.shared import json_contract_message as _json_contract_message

_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)\s*```", re.DOTALL | re.IGNORECASE)


class StructuredOutputError(ValueError):
    """JSON-prompt 结构化 LLM 响应无法校验时抛出。"""


def needs_json_prompt_structured_output(settings: Settings) -> bool:
    """对于应避免原生 ``response_format`` 的 provider 返回 True。

    校验刻意基于配置而非 model 类：本地 OpenAI 兼容 provider 都用
    ``ChatOpenAI``，所以运行时可用的稳定信号是 base URL / model 名。
    """

    marker = f"{settings.base_url} {settings.model}".lower()
    return "deepseek" in marker


def invoke_structured_json[ModelT: BaseModel](
    llm: BaseChatModel,
    messages: Sequence[BaseMessage],
    schema: type[ModelT],
) -> ModelT:
    """调用 ``llm`` 并从纯 JSON 响应解析一个 Pydantic 模型。"""

    response = llm.invoke([_json_contract_message(schema), *messages])
    text = _message_content_to_text(response.content)
    payload = _extract_json_object(text)
    try:
        return schema.model_validate(payload)
    except ValidationError as exc:
        msg = f"LLM JSON 未通过 {schema.__name__} 校验: {exc}"
        raise StructuredOutputError(msg) from exc


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
