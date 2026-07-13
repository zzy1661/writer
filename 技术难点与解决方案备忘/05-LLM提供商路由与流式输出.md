# LLM 提供商路由与流式输出

> **2026-07-08 重要修订**:本文档原描述基于"三档模型路由"(high/mid/low)的 L4 Provider 抽象,**该抽象从未实装**——当前 L4 直接用 LangChain `BaseChatModel`,通过 `WRITER_MODEL` / `WRITER_BASE_URL` / `WRITER_API_KEY` 环境变量切换具体模型。三档路由的诉求改由"按 directive 类别调不同 model"实现,但目前 **2 个 shipped directive (`/大纲` `/目录`) 都用同一模型**,未做分流(`/续写` `/改` 占位 SKILL.md 已于 2026-07-09 删除)。
>
> 真正落地的是:
>
> - **双 provider 路径**(per `writer.llm.structured.needs_json_prompt_structured_output`):native `bind_tools` / `with_structured_output` (OpenAI 兼容) vs JSON-prompt (DeepSeek 等)
> - **`ReActAgent` 多步工具循环**(`src/writer/llm/agent.py`):ReAct 风格,`MAX_LOOP_STEPS=5` 预算控制
> - **流式输出**:由 LangChain `BaseChatModel.astream()` 直接推 token;engine 把 chunk 透传到 REPL `TextChunk` 事件
>
> 本文以**新形态**重写。

## 业务背景

项目依赖 OpenAI 兼容协议。模型切换要简单(只改环境变量);章节正文、审核报告、SKILL.md directive 教学对模型能力和成本的要求不同,但目前 MVP 不分流。

## 技术难点

如果业务代码直接写模型名,后续切换 DeepSeek、Qwen、GLM 或私有 OpenAI 兼容服务会污染全链路。同时:

- 部分模型(deepseek-v3)支持原生 `bind_tools` / `with_structured_output`,可直接吐 Pydantic 实例
- 部分模型(老版本 DeepSeek、qwen 等)只支持 chat completion,要自己渲染 schema 进 prompt + JSON 解析
- 章节正文需要流式输出,而审核报告和大纲更适合一次性结构化返回
- 错误处理要区分网络失败、上下文超限、输出截断

## 解决方案

L4 是 LangChain `BaseChatModel`,通过 `WRITER_*` 环境变量切换 Provider;`writer.llm.get_llm(settings)` 返回当前模型实例。LLM 路由器(`LlmIntentRouter`)与 LLM 工具循环(`ReActAgent`)都基于这个统一入口。

### 双 provider 路径

`writer.llm.structured.needs_json_prompt_structured_output(settings)` 返回 True 时走 JSON-prompt:

- 系统 prompt 显式要求模型输出 `{}` 包裹的 JSON
- 用户 prompt 渲染 Pydantic schema 进内容(字段名 + 类型 + 描述)
- 模型响应后 `invoke_structured_json()` 用 regex / JSON 解析回 Pydantic 实例

否则走 native `bind_tools` / `with_structured_output`:

- `llm.with_structured_output(AgentAction)` 返回 `Runnable`
- `chain = COMMAND_AGENT_PROMPT | structured_llm`
- `chain.invoke({"user_input": ..., "project_state": ...})` 直接拿 `AgentAction`

切换条件由 `Settings` 派生(当前是模型名字符串匹配,可改成更严格的 capability 探测)。

### `ReActAgent` 多步循环

`src/writer/llm/agent.py`:

```python
MAX_LOOP_STEPS = 5

class ReActAgent:
    def __init__(self, settings, *, registry, runtime, llm=None, max_steps=MAX_LOOP_STEPS):
        ...

    async def run(self, action, ctx, deps, cfg) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done]: ...
```

`_parse_ai_message` 解析顺序:

1. `AIMessage.tool_calls`(native 路径,主路径)
2. `additional_kwargs._json_action`(JSON-prompt 路径)
3. content JSON(模型直接输出 JSON 字符串)
4. 最后兜底为 `answer_directly`(prose 内容也算 answer)

预算耗尽:

- 不抛异常
- 落 `TextChunk` 兜底文本 + `Done(reason="tool_loop_completed", payload={tool_calls_made, last_output})`
- **优雅耗尽**,与 `aborted` 区分(2026-07-08 新增 `tool_loop_completed` DoneReason)

`ToolError` 从循环内向上传播,让 engine 外层 `except ToolError` 兜底 → `ErrorEvent + Done(aborted)`。

### 流式输出

- LLM 路由器(`LlmIntentRouter.route`)目前是**一次性**调用,不走流式(命令路由的 latency 容忍度低)
- `ReActAgent` 当前也是**一次性**调用(等 LangGraph 真实落地后再考虑 stream token 到 `TextChunk` 事件)
- `EngineConfig.fast_mode` 抑制诊断 `[engine]` log chunks(2026-07-05 起)

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
- `/创作` 可以实时显示正文 token。
- `finish_reason=length` 时不盲目重试,而是给出明确错误。
