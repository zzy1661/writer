# LLM 提供商路由与流式输出

## 业务背景

项目依赖 OpenAI 兼容协议,但设计上要求支持 high/mid/low 三档模型。大纲、关键章节、校对、字数统计对模型能力和成本的要求不同。

## 技术难点

如果业务代码直接写模型名,后续切换 DeepSeek、Qwen、GLM 或私有 OpenAI 兼容服务会污染全链路。同时章节正文需要流式输出,而审核报告和大纲更适合一次性结构化返回。错误处理也要区分网络失败、上下文超限、输出截断。

## 解决方案

建立 L4 Provider 薄壳,Agent 核心只提交标准化 `ChatRequest`,不感知具体模型名。请求中只声明:

- `model_tier`:high、mid、low
- `response_format`:text 或 json
- `stream`:是否流式
- `temperature`、`max_tokens`、`messages`、`tools`

Provider 根据环境变量或用户配置把档位映射到具体模型。流式 token 通过事件回调上抛给会话控制层,再由 CLI Rich Live 渲染。

## 最小 demo / 伪代码

```python
from typing import Literal, TypedDict


class ChatRequest(TypedDict):
    model_tier: Literal["high", "mid", "low"]
    messages: list[dict]
    stream: bool
    response_format: Literal["text", "json"]


MODEL_BY_TIER = {
    "high": "deepseek-v3",
    "mid": "qwen-plus",
    "low": "qwen-turbo",
}


class LLMProvider:
    def chat(self, request: ChatRequest):
        model = MODEL_BY_TIER[request["model_tier"]]
        if request["stream"]:
            for token in openai_compatible_stream(model, request["messages"]):
                yield {"type": "token", "content": token}
        else:
            content = openai_compatible_chat(model, request["messages"])
            yield {"type": "message", "content": content}
```

## 核心依赖版最小代码

```python
from collections.abc import AsyncIterator

from openai import AsyncOpenAI
from pydantic import BaseModel


class ProviderSettings(BaseModel):
    base_url: str
    api_key: str
    high_model: str = "deepseek-v3"
    mid_model: str = "qwen-plus"
    low_model: str = "qwen-turbo"


class OpenAICompatibleProvider:
    def __init__(self, settings: ProviderSettings) -> None:
        self.settings = settings
        self.client = AsyncOpenAI(base_url=settings.base_url, api_key=settings.api_key)

    def select_model(self, tier: str) -> str:
        return {
            "high": self.settings.high_model,
            "mid": self.settings.mid_model,
            "low": self.settings.low_model,
        }[tier]

    async def stream_chat(self, tier: str, messages: list[dict]) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.select_model(tier),
            messages=messages,
            stream=True,
        )
        async for event in stream:
            token = event.choices[0].delta.content
            if token:
                yield token
```

## 落地建议

- 新增 `writer.llm.provider` 模块,定义 `ChatRequest`、`ChatResponse`、`LLMProvider` 协议。
- 支持 `WRITER_LLM_HIGH`、`WRITER_LLM_MID`、`WRITER_LLM_LOW`、`WRITER_LLM_BASE_URL`、`WRITER_LLM_API_KEY`。
- 章节正文默认 `stream=True`;大纲、审核、结构化报告默认 `stream=False`。
- 5xx 和网络错误指数退避;上下文超限触发压缩或降档;输出截断转人工。

## 验收标准

- L3 Agent 节点代码中不出现具体模型名。
- 切换 Provider 只需要改配置,不需要改写作流程代码。
- `/写` 可以实时显示正文 token。
- `finish_reason=length` 时不盲目重试,而是给出明确错误。
