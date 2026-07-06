"""LLM provider package.

Single source of truth for instantiating the language model consumed by
``IntentRouter`` (and later, roles/workflows). All router / role code must
import ``ChatOpenAI`` from here, never directly from ``langchain_openai``,
so the choice of provider stays in one place.
"""

from writer.llm.provider import LLMConfigError, get_llm
from writer.llm.structured import (
    StructuredOutputError,
    invoke_structured_json,
    needs_json_prompt_structured_output,
)

__all__ = [
    "LLMConfigError",
    "StructuredOutputError",
    "get_llm",
    "invoke_structured_json",
    "needs_json_prompt_structured_output",
]
