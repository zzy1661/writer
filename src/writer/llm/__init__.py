"""LLM provider package.

Single source of truth for instantiating the language model consumed by
``IntentRouter`` (and later, roles/workflows). All router / role code must
import ``ChatOpenAI`` from here, never directly from ``langchain_openai``,
so the choice of provider stays in one place.

Three LLM call paths are exposed:

* :mod:`writer.llm.structured` — short structured-output calls
  (Pydantic schema validated against a JSON response).
* :mod:`writer.llm.agent` — :class:`LLMToolLoop` ReAct-style tool calls.
* :mod:`writer.llm.prose` — :class:`LLMProseClient` for long-form prose
  generation (chapter drafts, review reports).
"""

from writer.llm.prose import (
    DeterministicProseClient,
    LLMProseClient,
    LLMProseError,
    RealProseClient,
)
from writer.llm.provider import LLMConfigError, get_llm
from writer.llm.structured import (
    StructuredOutputError,
    invoke_structured_json,
    needs_json_prompt_structured_output,
)

__all__ = [
    "DeterministicProseClient",
    "LLMConfigError",
    "LLMProseClient",
    "LLMProseError",
    "RealProseClient",
    "StructuredOutputError",
    "get_llm",
    "invoke_structured_json",
    "needs_json_prompt_structured_output",
]
