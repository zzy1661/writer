## Context

项目当前状态(2026-07-04):

- `pyproject.toml` 已声明 `langchain` / `langchain-openai` / `langgraph` 等所有 LLM 依赖。
- `src/writer/config/settings.py` 已提供 `Settings`(`WRITER_MODEL` / `WRITER_API_KEY` / `WRITER_BASE_URL` / `WRITER_TEMPERATURE`)和 `has_api_key` 检测。
- `src/writer/cli/main.py` 的 `writer doctor` 已能展示 API Key 是否配置。
- **仓库中没有任何代码实例化 LLM**(`ChatOpenAI` / `init_chat_model` 全部零结果)。
- `src/writer/routing/intent_router.py` 已落地 `IntentRouter` Protocol + `RuleBasedIntentRouter` MVP,后者只覆盖 `/写` / `/审核` / 含"伏笔"的输入 / 其他 `/` 前缀 / fallback `answer_directly`。
- `src/writer/engine/{loop,events,context,deps,config}.py` 已落 MVP:`run_engine` 是 `AsyncIterator[Event]`,事件类全部 `@dataclass(frozen=True)`,五种 `DoneReason` + `Done` 终结。但 `_engine_loop` 一次 dispatch 一个 Done,`call_tool` / `ask_user` / `ErrorEvent` 都是死分支。
- `src/writer/tools/{protocol,registry,runtime,builtin}/` 已落 5 个内置工具 + `built_tool_registry()` + LangChain 桥。

约束(per 备忘 16 §"已落地的 Engine 层结构"):

- `EngineDeps` 是 `@runtime_checkable Protocol`,扩展只能通过添加字段,不破坏现有 Protocol 表面。
- `run_engine` 仍是 `AsyncIterator[Event]`,不持有会话状态(留给未来的 `EngineSession`)。
- `EngineContext` / `EngineConfig` 全程 frozen,`EngineState` 是唯一可变对象。
- 测试基线 40 个全过,新增能力不破坏既有断言(除 `test_engine_yields_done_for_tool` 因为 `DoneReason` 扩了一员)。

干系人:

- CLI / REPL 消费者:关心 Done 分支稳定、事件流可渲染。
- 测试套件:关心 mock 友好、不引入网络依赖到既有测试。
- 未来的 LangGraph 工作流(备忘 04):关心 Engine Loop 准备好后 `start_workflow` 真能接图。

## Goals / Non-Goals

**Goals:**

- 让 `IntentRouter` Protocol 后面真有一个 LLM 实现,自然语言输入能解析为结构化 `AgentAction`。
- 让 Engine Loop 五种 `AgentAction` 分支全部活起来:`call_tool` 真调工具、`ask_user` 真发 `Interrupt`、异常被捕获为 `ErrorEvent`、Ctrl+C 体现为 `Done(aborted)`。
- 加 `tool_completed` DoneReason,语义准确反映"工具已执行完"。
- `production_deps()` 根据 API key 智能切换路由器,缺 key 时回退规则版(零网络可跑)。
- **规则优先 + LLM fallback** 模式:`/` 前缀明确命令零 token,自然语言才调 LLM,降低 token 消耗与延迟。
- LLM 异常(Pydantic 校验失败 / API 超时 / 429)fallback 到 `RuleBasedIntentRouter`,不让用户因为 LLM 抖动得到错误路由。

**Non-Goals:**

- 不接 LangGraph `StateGraph`(后续 change 单独做,备忘 04)。
- 不实现会话级 `EngineSession` 与跨 turn checkpoint(后续 change,备忘 17)。
- 不改 `StoryConsultant.draft_outline()` 接入真实 LLM(留待后续,本次只让 `IntentRouter` 有 LLM 实现)。
- 不重写 CLI/REPL 的渲染(本次只保证事件流正确,渲染细节留给 cli 层)。
- 不引入 RAG / 上下文压缩(待 LLM 真接后再排)。

## Decisions

### D1: LLM Provider 独立成 `src/writer/llm/` 包

**选择**: 新增 `src/writer/llm/provider.py`,导出 `get_llm(settings: Settings) -> ChatOpenAI`,不在 `routing/` 或 `engine/` 内部 `import ChatOpenAI`。

**理由**: LLM 选型与配置属于"基础设施"层,跨 router / role / workflow 共用。独立包后,未来切换 `ChatAnthropic` / 本地 vLLM / Azure OpenAI 只改一个文件。LangChain `ChatOpenAI` 已经支持 `base_url` 参数,可平替 DeepSeek / Moonshot 等 OpenAI 兼容 API(`Settings.base_url` 默认 OpenAI,用户改 `.env` 即可)。

**备选**: 在 `routing/llm_router.py` 顶部直接 `from langchain_openai import ChatOpenAI` 并实例化。被否,因为 router 不应承担 LLM 选型职责,且未来 `StoryConsultant` 接入 LLM 时需要共享实例化逻辑。

### D2: 规则优先 + LLM fallback 落地为 `CompositeRouter`

**选择**: 新增 `src/writer/routing/composite_router.py`,类签名:

```python
class CompositeRouter(IntentRouter):
    def __init__(self, primary: RuleBasedIntentRouter, fallback: LlmIntentRouter) -> None: ...
    def route(self, user_input: str, project_state: str) -> AgentAction: ...
```

`RuleBasedIntentRouter.route()` 在当前实现下,对纯 `/` 前缀命令返回 `run_command` / `start_workflow`,对其他自然语言返回 `answer_directly` 模板。**但是**它的 fallback 太激进——任何非命令式输入都被降级。

**改法**: 给 `RuleBasedIntentRouter` 加一个 `_looks_like_command(text) -> bool` 谓词:

- 命中 `/` 前缀 → True(零 token,直接返回)
- 命中 `text in {"init", "状态", "退出", "帮助"}` 这种纯关键词 → True
- 否则 → False,`CompositeRouter` 才会去问 LLM

`LlmIntentRouter` 只在 `primary.looks_like_command(text) is False` 时被调;LLM 异常时 `CompositeRouter` 仍 fallback 到 `RuleBasedIntentRouter` 的 `answer_directly` 模板,确保不抛异常出 engine。

**理由**: 这是"高频命令零成本、低频自然语言花 token"的省 token 模式,同时 LLM 失败不影响用户。规则版作为 fallback 兜底,等价于"系统退化模式"。

**备选 A**: 让 `RuleBasedIntentRouter` 对所有非 `/` 前缀输入直接返回 `answer_directly` 模板,不调 LLM。简单,但用户问"主角人设太弱,改一下"时永远只能看到模板。
**备选 B**: 让 `LlmIntentRouter` 是主路径,规则只是 LLM 失败时的兜底。省开发但费 token,所有命令都打 API。

### D3: `call_tool` 真调后改 `DoneReason="tool_completed"`

**选择**: `DoneReason` 增加字面量 `"tool_completed"`;`_engine_loop` 在 `call_tool` 分支依次 yield:

```
TextChunk("[engine] 工具 {name} 调用中…")
ToolCall(name=action.tool_name, arguments=action.arguments)
   └── registry.invoke(name, runtime, **action.arguments)  # 可能抛 ToolError
ToolResult(name=action.tool_name, output=result.output)
TextChunk("[engine] 工具 {name} 完成")
Done(reason="tool_completed", payload={"tool": name, "output": result.output})
```

`ToolError`(包含 `ToolNotFoundError` / `ToolDeniedError` / `ToolOutputTooLargeError`)被 try/except 捕获,转为 `ErrorEvent(message=str(e))` + `Done(aborted)`。

**理由**: 旧名 `tool_pending` 语义已不准(工具其实已执行完),改名最清楚。

**备选 A**: 保留 `tool_pending`,只多 yield `ToolCall` / `ToolResult` 事件。语义不准(pending 暗示"还没做")。
**备选 B**: 完全去掉 `tool_pending`,所有工具调用统一走 `answered` Done。丢失"工具路径 vs 文本回答"的区分。

### D4: `Interrupt` + `Done(ask_user)` 一次轮走两步

**选择**: `_engine_loop` 在 `ask_user` 分支 yield:

```
TextChunk("[engine] 需要用户补充: {prompt}")
Interrupt(type="text", prompt=prompt, options=None)
Done(reason="ask_user", payload={"prompt": prompt})
```

`Interrupt` 事件被 CLI 渲染为提示符,用户在 REPL 输入答案后由 CLI driver 构造新的 `EngineContext(user_input=answer)` 重新调 `run_engine`。`Interrupt` 是**信号事件**而非"等待输入"——AsyncGenerator 不能阻塞读 stdin,会话驱动属于上层 REPL 职责。

**理由**: 维持"一轮 = 一次 AsyncGenerator"的契约,REPL driver 负责拼装多轮对话。

**备选**: 让 engine 内部用 `asyncio` 任务读 stdin 阻塞,直到拿到答案再 yield 最终结果。破坏"engine 是 stateless AsyncGenerator"的契约,测试变得困难。

### D5: `ToolRuntime` 在 `project_root=None` 时用 sentinel fallback

**选择**: `production_deps()` 收到 `ctx.project_root=None` 时,构造 `ToolRuntime(project_root=Path("/__no_project__"))`。`safe_path` 保持原逻辑(任何路径都会触发越界检查失败),但在 S0 路径下,只有不需要 project_root 的工具(`foreshadow_query` / `chapter_locate` / `wordcount`)可用;文件读写类工具(`safe_read_file` / `safe_list_dir`)触发 `ToolDeniedError`,被 loop 转成 `ErrorEvent` + `Done(aborted)`。

**理由**: 不需要为 S0 改 `ToolRuntime` 内部逻辑,Tool 各自管自己的 project_root 需求,Engine 只负责把异常接住。

**备选 A**: S0 时不构造 `ToolRuntime`,call_tool 直接 yield `ErrorEvent("S0 不能调工具")`。语义清楚但会让伏笔查询这种"全局"工具在 S0 不可用。
**备选 B**: `ToolRuntime` 加 `is_active: bool` 字段,S0 时 False,`safe_path` 跳过检查。改动 `ToolRuntime` 公共表面。

### D6: `EngineConfig.fast_mode` 压制 `[engine]` log chunks

**选择**: `_engine_loop` 在 `cfg.fast_mode=True` 时跳过 yield `TextChunk("[engine] …")` 这类诊断信息(保留 `ActionEvent` / `ToolCall` / `ToolResult` / `Done` 等业务事件)。`cfg.fast_mode` 默认 `False`,不影响现有测试。

**理由**: 用户调用 `uv run writer --fast` 或类似开关时,希望减少噪音。Engine 层做压制,CLI 层不做事件过滤。

## Risks / Trade-offs

- **[LLM 抖动污染路由]**: LangChain `with_structured_output` 在模型返回 schema 不合规时会抛 ValidationError。→ CompositeRouter 捕获后 fallback 到 RuleBasedIntentRouter,不冒泡出 engine。
- **[Token 成本]**: 自然语言输入每次调 LLM,长会话累计 token 不可忽略。→ 规则优先模式把高频 `/` 命令零成本化;后续可在 `CompositeRouter` 加 LRU 缓存(本次不做)。
- **[S0 sentinel 路径可能被绕]**: `ToolRuntime(project_root="/__no_project__")` 下,`safe_read_file(path="/etc/passwd")` 会被越界检查拦下,但 `safe_read_file(path="something_relative")` 在 sentinel root 下会 resolve 到 `/__no_project__/something_relative`,然后 read 失败(`FileNotFoundError`)而非 `ToolDeniedError`。→ 这种 ToolError 由 loop 转成 `ErrorEvent`,用户能看出"文件不存在"而非"路径越界",可接受。
- **[DoneReason 字面量扩员]**: 下游若用 `match` 穷尽匹配,需补 `tool_completed` case。→ 当前代码无 `match`,文档 `命令与用户流程.md` 后续归档时同步更新。
- **[测试 mock 复杂度]**: `LlmIntentRouter` 依赖 LangChain `with_structured_output` chain,单测需要 mock `ChatPromptTemplate | ChatOpenAI` chain。→ `langchain_core` 提供 `FakeChatModel` / `FakeListLLM` 可平替,测试写在 `tests/test_routing_llm.py` 隔离。
- **[engine/loop.py 改动面大]**: 一次性接活 4 个分支(call_tool / ask_user / error / fast_mode),回归风险高。→ `tests/test_engine.py` 加 4 个新测试分别覆盖每条分支,既有 39 个不动。

## Migration Plan

无版本迁移需要(项目尚未发布)。部署步骤就是合并到 main。

回滚策略:本次 change 不引入新数据库 schema / 配置文件,回滚 = revert commit。`DoneReason` 新增的字面量在 revert 后下游不再收到该值,与未变更时一致。

## Open Questions

- **Q1**: `LlmIntentRouter` 在 Pydantic schema 校验失败时,是否应该在 fallback 到规则版的同时 yield 一个 `TextChunk("LLM 路由回退到规则版,原因: …")`?目前的设想是"静默 fallback",但用户可能疑惑为何 LLM 没起作用。→ 倾向 yield 一行 diagnostic TextChunk,但不在 Done payload 里区分。本次落地。
- **Q2**: `CompositeRouter` 是否需要把"规则判不了"的输入 batch 起来延迟调 LLM?例如用户连续发 3 条自然语言,合并成一次 LLM 调用。→ 不在本次范围。MVP 先做"单条立即调"。
- **Q3**: `EngineState` 本次是否填字段?备忘 16 说"目前 MVP 还没填字段,留类不填实例,等 continue 站点接入(per 03 + 06)时直接长出来"。→ 本次保持空 class,不动。
- **Q4**: LLM Provider 包后续是否需要支持多模型路由(不同 role 用不同模型)?→ 留给未来。本次只一个全局 `get_llm()`。