# 09 · LLM 工具循环(ReAct + 双 Provider)

> 对应代码:`src/writer/llm/{agent,provider,structured,prose}.py`
> 设计备忘:[`备忘 05-LLM提供商路由`](../../技术难点与解决方案备忘/05-LLM提供商路由与流式输出.md) + [`备忘 12-RAG与检索`](../../技术难点与解决方案备忘/12-RAG与检索实现方案.md)

---

## 9.1 设计动机

**问题**:`LlmIntentRouter` 是**单次翻译器**(用户输入 → `AgentAction`),但很多任务需要**多步工具调用**——

> 用户:「搜一下伏笔 F003,告诉我它在第几章被回收」

按单次翻译模型,LLM 只能产出 `call_tool(foreshadow_search, {id: "F003"})`,然后工具返回结果,但 LLM 看不到结果(已经退出了),要再问一次,才能把结果整理成答案。

**ReAct 模式**:**让 LLM 在同一轮 turn 内完成多步**——LLM 看到工具结果,继续决策(再调工具 / 给出答案),直到任务完成或预算耗尽。

**两条 provider 路径**:

1. **native `bind_tools`**(OpenAI 兼容):模型支持原生结构化输出,直接 `bind_tools(tools)` 拿 `AIMessage.tool_calls`
2. **JSON-prompt fallback**(DeepSeek 等):模型不支持原生 tool binding,把工具目录序列化进 system prompt,要求模型输出 JSON,后端解析回 `AgentAction`

切换条件:`needs_json_prompt_structured_output(settings)`(启发式:模型名含 "deepseek" → True)。

## 9.2 `LLMToolLoop` 类

> 对应代码:`src/writer/llm/agent.py`

```python
MAX_LOOP_STEPS = 5  # 每轮工具调用硬上限


@dataclass
class ToolLoopState:
    """LLM 工具循环的每轮状态。生命周期为单轮。"""
    messages: list[BaseMessage] = field(default_factory=list)
    tool_calls_made: int = 0
    last_tool_result: ProtocolToolResult | None = None


class LLMToolLoop:
    def __init__(
        self,
        settings: Settings,
        registry: ToolRegistry,
        runtime: ToolRuntime,
        *,
        llm: BaseChatModel | None = None,
        langchain_tools: list[BaseTool] | None = None,
    ):
        self._settings = settings
        self._registry = registry
        self._runtime = runtime
        self._descriptors = list(registry.describe())
        self._use_json_prompt = needs_json_prompt_structured_output(settings)
        self._llm = llm or get_llm(settings)
        self._tools = langchain_tools or to_langchain_tools(registry, runtime)
        self._bound_llm = (
            self._llm.bind_tools(self._tools) if not self._use_json_prompt else None
        )
```

### 构造选项

| 参数 | 用途 | 谁会传 |
| ---- | ---- | ------ |
| `settings` | 必传;读 model / api_key / base_url | 生产装配 |
| `registry` | 必传;Tool 注册表 | 生产装配 |
| `runtime` | 必传;每次调用都会经过 | 生产装配 |
| `llm` | 测试注入 fake | 测试 |
| `langchain_tools` | 测试注入;绕过 `to_langchain_tools` 闭包 | 测试 |

### 字段

- **`self._use_json_prompt`**:True → 走 JSON-prompt 路径;False → 走 native `bind_tools`
- **`self._bound_llm`**:仅 native 路径下非 None;`_invoke_model` 用它
- **`self._tools`**:`to_langchain_tools(registry, runtime)` 把所有 builtin Tool 包装为 LangChain `StructuredTool`

## 9.3 `run()` — ReAct 主循环

```python
async def run(
    self, action: AgentAction, ctx: EngineContext, deps: EngineDeps, cfg: EngineConfig
) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done]:
    state = ToolLoopState(
        messages=self._initial_messages(action, ctx.user_input, deps=deps),
    )

    while state.tool_calls_made < MAX_LOOP_STEPS:
        ai_message = await self._invoke_model(state.messages)
        state.messages.append(ai_message)

        parsed = self._parse_ai_message(ai_message)
        if parsed is None:
            # 软失败:模型没产出可执行动作
            yield TextChunk(text="LLM 未产出可执行动作...")
            yield Done(reason="tool_loop_completed", payload={"tool_calls_made": 0, "fallback": "no_action"})
            return

        if parsed.action_type == "answer_directly":
            yield TextChunk(text=parsed.answer or "")
            yield Done(reason="answered", payload={"answer": parsed.answer, "tool_calls_made": state.tool_calls_made})
            return

        # call_tool
        tool_name = parsed.tool_name or ""
        arguments = dict(parsed.arguments)
        yield ToolCall(name=tool_name, arguments=arguments)

        # 故意让 ToolError 向外传播 → engine except ToolError 兜底
        result = self._registry.invoke(tool_name, self._runtime, **arguments)
        state.last_tool_result = result
        state.messages.append(self._build_tool_message(ai_message, tool_name, result.output))
        yield ToolResult(name=tool_name, output=result.output)
        state.tool_calls_made += 1

    # 预算耗尽 → 优雅退出,不算失败
    fallback_text = self._budget_fallback(state)
    yield TextChunk(text=fallback_text)
    yield Done(reason="tool_loop_completed", payload={"tool_calls_made": state.tool_calls_made, "last_output": ...})
```

### 关键设计

- **`MAX_LOOP_STEPS = 5`** —— 硬上限,防病态模型无限循环
- **`ToolError` 外溢** —— 不在循环内吞异常,让 engine 外层 `except ToolError` 统一兜底
- **预算耗尽 = `tool_loop_completed`** —— **优雅耗尽**,与 `aborted` 区分,不算 failed

## 9.4 `_initial_messages` — System Prompt 拼接(per Bug 02 修复)

```python
def _initial_messages(self, action, user_input, *, deps) -> list[BaseMessage]:
    system_parts: list[str] = [self._system_prompt()]

    # 1. directive body
    if action.action_type == "answer_directly" and action.command:
        directive_meta = deps.directive_registry.get(action.command)
        if directive_meta is not None:
            refs = "\n\n".join(f"--- {relpath} ---\n{body}" for relpath, body in directive_meta.references.items())
            section = f"[directive body: {directive_meta.command}]\n{directive_meta.body}"
            if refs:
                section += f"\n\n[directive references]\n{refs}"
            if directive_meta.extra_instructions:
                section += f"\n\n[project-level extra instructions]\n{directive_meta.extra_instructions}"
            system_parts.append(section)

    # 2. agent identity
    if action.target_agent:
        agent_meta = deps.agent_registry.get(action.target_agent)
        if agent_meta is not None:
            system_parts.append(f"[agent identity: {agent_meta.name}]\n{agent_meta.body}")

    # 3. router hint
    if action.answer:
        system_parts.append(f"[router hint]\n{action.answer}")

    return [
        SystemMessage(content="\n\n".join(system_parts)),
        HumanMessage(content=user_input),
    ]
```

### 拼接顺序

```
[base system prompt]
[directive body: /大纲]
[directive references]
[project-level extra instructions]   ← per chg-project-skills
[agent identity: 历史题材 Agent]
[router hint]
[HumanMessage: 主角修仙]
```

LLM 同时看到「循环规则 + 命令指令 + agent 身份 + 用户原始输入」。

### Bug 02 修复历史

**之前**:`_initial_messages` 只发 base system prompt + user input,LLM 完全不知道 SKILL.md body / agent body → LLM 当普通 `answer_directly` 处理,直接编大纲,不调 tool。

**修复**:2026-07-09 commit `e040d6a`,在 `_initial_messages` 里加上 directive body + agent identity 拼接。Engine `_run_directive` 构造的 `AgentAction(action_type="answer_directly", command="/大纲", answer=directive.body)` 在循环里被识别为 directive 调用,LLM 读到 body。

## 9.5 `_system_prompt` — 循环规则 + 工具目录

```python
def _system_prompt(self) -> str:
    catalog = json.dumps(
        [{"name": d.name, "description": d.description} for d in self._descriptors],
        ensure_ascii=False,
    )
    return (
        "你是 Writer Agent 的工具循环(ReAct-style)。\n"
        "你的任务是:\n"
        "1. 阅读用户输入与对话历史(含历史 tool 结果)。\n"
        "2. 决定下一步:\n"
        "   - 调用工具 → 输出 {\"action_type\":\"call_tool\","
        " \"tool_name\": \"<name>\", \"arguments\": {...}}\n"
        "   - 给出最终回答 → 输出 {\"action_type\":\"answer_directly\","
        " \"answer\": \"<text>\"}\n"
        f"可用工具目录:\n{catalog}\n"
    )
```

**关键**:`catalog` 渲染为 JSON 块,JSON-prompt 路径必须依赖它来选工具;native 路径忽略,但保留作为 prompt hint。

## 9.6 `_invoke_model` — 双 provider 路径

```python
async def _invoke_model(self, messages: list[BaseMessage]) -> AIMessage:
    if self._use_json_prompt:
        assert self._llm is not None
        parsed = invoke_structured_json(self._llm, messages, AgentAction)
        return AIMessage(
            content=parsed.model_dump_json(),
            additional_kwargs={"_json_action": parsed},
        )
    assert self._bound_llm is not None
    ai_message = await self._bound_llm.ainvoke(messages)
    if not isinstance(ai_message, AIMessage):
        ai_message = AIMessage(content=str(ai_message.content))
    return ai_message
```

### Native path(`_use_json_prompt=False`)

```python
self._bound_llm = self._llm.bind_tools(self._tools)
ai_message = await self._bound_llm.ainvoke(messages)
# ai_message.tool_calls 是结构化 tool_call 列表
```

OpenAI 兼容协议:模型看到 `tools` 字段(来自 `bind_tools`),产出 `AIMessage(content=..., tool_calls=[{name, args, id}, ...])`。

### JSON-prompt path(`_use_json_prompt=True`)

```python
parsed = invoke_structured_json(self._llm, messages, AgentAction)
# parsed 是 Pydantic AgentAction 实例
return AIMessage(content=parsed.model_dump_json(), additional_kwargs={"_json_action": parsed})
```

模型看到 system prompt 里手写的指令 + 工具目录 JSON,产出 JSON 文本,后端用 Pydantic schema 校验。**`_json_action` 字段让 `_parse_ai_message` 直接拿,不再 re-parse**。

### `invoke_structured_json`

> 对应代码:`src/writer/llm/structured.py`

```python
def invoke_structured_json(llm, messages, schema: type[BaseModel]) -> BaseModel:
    """要求模型输出 JSON,后端用 Pydantic schema 校验并实例化。"""
    schema_json = schema.model_json_schema()
    # 在 messages 末尾追加一个 system reminder:「请按以下 schema 输出 JSON」
    messages = messages + [
        SystemMessage(content=f"请严格按以下 JSON schema 输出:\n{json.dumps(schema_json, ensure_ascii=False, indent=2)}")
    ]
    response = llm.invoke(messages)
    # 提取 content 中的 JSON(可能有 markdown ```json 包裹)
    text = _extract_json(response.content)
    return schema.model_validate_json(text)
```

**关键**:`schema.model_json_schema()` 拿到 Pydantic schema JSON,直接渲染进 prompt,模型按 schema 输出。

## 9.7 `_parse_ai_message` — 四级解析顺序

```python
def _parse_ai_message(self, ai_message: AIMessage) -> AgentAction | None:
    # 1. AIMessage.tool_calls — 原生 binding 路径
    tool_calls = getattr(ai_message, "tool_calls", None) or []
    if tool_calls:
        first = tool_calls[0]
        tool_name = str(first.get("name", "") or "")
        raw_args = first.get("args", {}) or {}
        arguments = dict(raw_args) if isinstance(raw_args, dict) else {}
        if tool_name:
            return AgentAction(action_type="call_tool", tool_name=tool_name, arguments=arguments)

    # 2. additional_kwargs["_json_action"] — JSON-prompt 路径(已校验)
    json_action = ai_message.additional_kwargs.get("_json_action")
    if isinstance(json_action, AgentAction):
        return json_action

    # 3. content 解析为 JSON
    content = ai_message.content
    text_content = ""
    if isinstance(content, str):
        text_content = content
    elif isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                text = item.get("text") or item.get("content")
                if isinstance(text, str):
                    parts.append(text)
        text_content = "\n".join(parts)

    stripped = text_content.strip()
    if stripped:
        try:
            payload = json.loads(stripped)
            if isinstance(payload, dict) and "action_type" in payload:
                return AgentAction.model_validate(payload)
        except json.JSONDecodeError:
            pass
        # 4. 纯文本 → 视为 answer_directly
        return AgentAction(action_type="answer_directly", answer=text_content)

    return None
```

### 解析顺序

1. **`tool_calls`**(原生 binding):首选
2. **`_json_action`**(JSON-prompt):次选,已经预校验
3. **`content` 解析为 JSON**(content 里恰好是 JSON):兜底
4. **`content` 是纯文本**:视为 `answer_directly`,让 ReAct 循环干净终止
5. **`None`**(空 content + 无 tool_calls):软失败,fallback 兜底

### 关键设计

- **`tool_calls` 只取第一个**(`first = tool_calls[0]`):防止模型一次性发多个 tool call 时只调一个
- **多段 content 处理**:新版 LC provider 返回 `content: list[dict]`,需要逐段提取文本
- **JSON 解析失败不算错**:模型用散文回答是合法路径,直接当 answer

## 9.8 `_build_tool_message` — 工具结果回填

```python
def _build_tool_message(self, ai_message, tool_name, output) -> ToolMessage:
    """把工具结果包装为 ToolMessage 给模型。"""
    tool_call_id = ""
    tool_calls = getattr(ai_message, "tool_calls", None) or []
    for entry in tool_calls:
        if str(entry.get("name", "") or "") == tool_name:
            tool_call_id = str(entry.get("id", "") or "")
            break
    if not tool_call_id:
        # JSON-prompt 路径:合成 id
        tool_call_id = f"{tool_name}-{len(self._descriptors)}"
    return ToolMessage(content=output, tool_call_id=tool_call_id)
```

**关键**:原生 provider 要求 `tool_call_id` 与 `AIMessage.tool_calls[i].id` 配对;JSON-prompt 路径下没有真实 id,合成一个。

## 9.9 `_budget_fallback` — 预算耗尽兜底

```python
def _budget_fallback(self, state: ToolLoopState) -> str:
    head = (
        f"工具调用已达上限 ({state.tool_calls_made}/{MAX_LOOP_STEPS});"
        " 请基于以下最近结果继续追问或缩小范围："
    )
    last = state.last_tool_result.output if state.last_tool_result else "(无)"
    tail = last if len(last) <= 200 else last[:200] + "..."
    return f"{head}\n{tail}"
```

**为什么 200 字符**:避免把巨型 payload 推回给用户(可能 OOM);同时给用户足够上下文继续追问。

## 9.10 `LLMProseClient` — 章节正文生成

> 对应代码:`src/writer/llm/prose.py`

章节正文生成是另一个独立 client(不通过 LLMToolLoop)。

```python
class LLMProseClient(Protocol):
    name: Literal["real", "deterministic"]

    def generate_chapter(
        self,
        *,
        outline: str,
        characters: str,
        chapter_title: str,
        chapter_index: int,
        prior_chapter_summary: str,
        temperature: float = 0.7,
        max_tokens: int = 4000,
    ) -> str:
        ...


class RealProseClient:
    name = "real"

    def __init__(self, llm: BaseChatModel):
        self._llm = llm

    def generate_chapter(self, **kwargs) -> str:
        prompt = _build_prose_prompt(**kwargs)
        response = self._llm.invoke(prompt)
        return response.content


class DeterministicProseClient:
    name = "deterministic"

    def generate_chapter(self, **kwargs) -> str:
        # 测试/无 API key 部署:返回固定模板
        return (
            f"# {kwargs['chapter_title']}\n\n"
            f"(本章由 DeterministicProseClient 生成,基于大纲片段:\n{kwargs['outline'][:200]}...)\n"
        )
```

**`production_deps` 的切换**:

```python
if resolved.has_api_key:
    prose_client = RealProseClient(llm=_get_llm(resolved))
else:
    prose_client = DeterministicProseClient()
```

Engine / workflow 通过 `deps.prose_client.name`(`"real"` vs `"deterministic"`)分支,而不是判断 API key。

## 9.11 `provider.get_llm` — LangChain ChatModel 工厂

> 对应代码:`src/writer/llm/provider.py`

```python
def get_llm(settings: Settings) -> BaseChatModel:
    """根据 settings 构造 LangChain ChatModel。

    支持:
    - OpenAI 兼容协议(WRITER_BASE_URL + WRITER_API_KEY + WRITER_MODEL)
    - 未来 Anthropic / 本地模型(可在此扩展)
    """
    from langchain_openai import ChatOpenAI
    return ChatOpenAI(
        model=settings.model,
        api_key=settings.api_key,
        base_url=settings.base_url,
        temperature=settings.temperature,
    )
```

**关键**:**L3 引擎 / L4 Provider 通过 LangChain `BaseChatModel` 接口解耦**——L3 不知道模型是 OpenAI / DeepSeek / Claude。

## 9.12 `needs_json_prompt_structured_output`

> 对应代码:`src/writer/llm/structured.py`

```python
def needs_json_prompt_structured_output(settings: Settings) -> bool:
    """某些 provider 拒绝 native tool binding,需要 fallback 到 JSON-prompt。

    启发式判断:模型名含 "deepseek" → True(已知不支持)。
    """
    return "deepseek" in settings.model.lower()
```

**为什么不检测所有 provider**:每次加 provider 都改这里很脆;先用启发式,未来可改 `Settings.native_tool_binding: bool` 字段。

## 9.13 完整数据流:用户输入「查一下伏笔 F003,告诉我它在第几章被回收」

```
LLM IntentRouter 产出 AgentAction(call_tool, tool_name="foreshadow_search", arguments={"id": "F003"})
   ↓
Engine:
    if deps.tool_loop is not None:
        async for event in _run_tool_loop(action, ctx, deps, cfg):
            yield event
   ↓
_run_tool_loop:
    async for event in deps.tool_loop.run(action, ctx, deps, cfg):
        yield event
   ↓
LLMToolLoop.run():
    state = ToolLoopState(messages=[
        SystemMessage(base + router hint),
        HumanMessage("查一下伏笔 F003,告诉我它在第几章被回收"),
    ])

    # 第一轮
    ai = await self._invoke_model(state.messages)
    parsed = self._parse_ai_message(ai)
    # parsed.action_type == "call_tool", tool_name="foreshadow_search"
    yield ToolCall(name="foreshadow_search", arguments={"id": "F003"})
    result = registry.invoke("foreshadow_search", runtime, id="F003")
    # result.output = "F003: 玉佩真实来历 (状态:已回收, 章节:1.5)"
    state.messages.append(ToolMessage(content=result.output, tool_call_id="foreshadow_search-9"))
    yield ToolResult(name="foreshadow_search", output=result.output)
    state.tool_calls_made = 1

    # 第二轮 — LLM 看到工具结果
    ai = await self._invoke_model(state.messages)
    parsed = self._parse_ai_message(ai)
    # parsed.action_type == "answer_directly", answer="F003 玉佩真实来历在第 1.5 章被回收..."
    yield TextChunk(text=parsed.answer)
    yield Done(reason="answered", payload={"answer": parsed.answer, "tool_calls_made": 1})
```

---

## 9.14 进一步阅读

- [04-意图路由层](04-意图路由层.md) —— `LlmIntentRouter` 与 `CompositeRouter`
- [06-Tool层与Runtime](06-Tool层与Runtime.md) —— Tool 协议 + LangChain 桥接
- [备忘 05-LLM提供商路由](../../技术难点与解决方案备忘/05-LLM提供商路由与流式输出.md)