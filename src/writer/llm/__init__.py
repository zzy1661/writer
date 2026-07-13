"""LLM provider 包。

实例化语言模型的单一真理来源，被 ``IntentRouter``（以及未来的
roles / workflows）消费。所有 router / role 代码必须从这里导入
``ChatOpenAI``，而不是直接从 ``langchain_openai``，让 provider 的
选择保持在一处。

暴露三条 LLM 调用路径：

* :mod:`writer.llm.structured` —— 短结构化输出调用（针对 JSON 响应
  校验 Pydantic schema）。
* :mod:`writer.llm.agent` —— :class:`ReActAgent` ReAct 风格的工具调用。
* :mod:`writer.llm.prose` —— :class:`LLMProseClient` 长篇散文生成
  （章节草稿、审阅报告）。
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
