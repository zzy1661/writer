"""Shared prompt utilities — the JSON-contract fallback for non-``response_format`` providers.

Originally implemented as a private helper ``_json_contract_message``
inside :mod:`writer.llm.structured`. Some OpenAI-compatible providers
(notably DeepSeek at the time this was added) reject the
``response_format`` payload emitted by LangChain's native structured
output path. The fallback asks the model for plain JSON and validates
the response locally against a Pydantic schema.

The contract is template-shaped so it can live in the registry like any
other prompt. The JSON schema is rendered at call time rather than at
template construction time, because the schema itself is supplied by
the caller (different call sites use different Pydantic models).
"""

from __future__ import annotations

import json

from langchain_core.messages import SystemMessage
from pydantic import BaseModel


def json_contract_message(schema: type[BaseModel]) -> SystemMessage:
    """Return the system message that asks an LLM to emit a JSON object
    matching ``schema``.

    The message is produced on demand (not at module import time) because
    the schema is supplied per call. Callers feed the result to the LLM
    via :func:`writer.llm.structured.invoke_structured_json`.
    """

    schema_json = json.dumps(schema.model_json_schema(), ensure_ascii=False)
    return SystemMessage(
        content=(
            "你必须只输出一个合法 JSON 对象，不要输出 Markdown、解释、代码围栏或额外文本。\n"
            f"JSON 必须符合这个 Pydantic schema: {schema_json}"
        )
    )


__all__ = ["json_contract_message"]
