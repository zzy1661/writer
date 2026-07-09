"""共享 prompt 工具 —— 不支持 ``response_format`` 的 provider 的 JSON 契约回退。

最初作为私有 helper ``_json_contract_message`` 实现在
:mod:`writer.llm.structured` 中。一些 OpenAI 兼容 provider（尤其是
添加本模块时的 DeepSeek）会拒绝 LangChain 原生结构化输出路径产出的
``response_format`` payload。回退路径向模型请求纯 JSON 并在本地
针对 Pydantic schema 校验响应。

契约是模板形态的，因此可以像其他 prompt 一样在 registry 中存在。
JSON schema 在调用时而非模板构造时渲染，因为 schema 本身由调用方
提供（不同调用点使用不同 Pydantic 模型）。
"""

from __future__ import annotations

import json

from langchain_core.messages import SystemMessage
from pydantic import BaseModel


def json_contract_message(schema: type[BaseModel]) -> SystemMessage:
    """返回要求 LLM 输出匹配 ``schema`` 的 JSON 对象的 system message。

    该消息按需产生（而非在模块 import 时），因为 schema 由每次调用
    提供。调用方通过 :func:`writer.llm.structured.invoke_structured_json`
    把结果喂给 LLM。
    """

    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return SystemMessage(
        content=(
            "你必须只输出一个合法 JSON 对象，不要输出 Markdown、解释、代码围栏或额外文本。\n"
            f"JSON 必须符合这个 Pydantic schema: {schema_json}"
        )
    )


__all__ = ["json_contract_message"]
