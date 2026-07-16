## Why

项目已经装好 LangChain / langchain-openai / langgraph 等所有 LLM 依赖,Settings 也准备好了 `WRITER_MODEL/API_KEY/BASE_URL/TEMPERATURE` 环境变量,但**仓库中没有任何代码实例化 LLM**(已 grep 验证 `ChatOpenAI` / `ChatAnthropic` / `init_chat_model` 均零结果)。Engine Loop 当前的 `_engine_loop` 是单发 dispatch: `call_tool` / `ask_user` / `ErrorEvent` / `Done(aborted)` 全是死分支(事件类已定义,loop 从不 emit)。

这两个缺口必须一起补: LLM 接进来后,路由会输出 `call_tool` / `start_workflow` 等更智能的 `AgentAction`,但引擎不真执行,用户看到的"LLM 说要查伏笔,引擎立刻 Done"比纯规则版更糟。同步落地才能让用户看到端到端价值(自然语言 → 路由 → 真调工具 → 返回结果)。

## What Changes

- 新增 `src/writer/llm/` 包:`provider.py` 提供 `get_llm(settings) -> ChatOpenAI` factory,Settings 驱动,可被 mock。
- 新增 `src/writer/routing/llm_router.py`:`LlmIntentRouter(IntentRouter)`,基于 LangChain `with_structured_output(AgentAction)` + `COMMAND_AGENT_PROMPT`。
- 新增 `src/writer/routing/composite_router.py`:**规则优先 + LLM fallback** 复合路由器,高置信度(`/` 前缀明确命令、`/init`、`/状态`、`/退出`)走规则零 token,其他自然语言才调 LLM。
- 修改 `src/writer/engine/loop.py` 接活:
  - `call_tool` 分支: yield `ToolCall` + 真调 `registry.invoke()` + yield `ToolResult` + `Done(reason="tool_completed", payload={"tool": name, "output": ...})`
  - `ask_user` 分支: yield `Interrupt(type, prompt, options)` + `Done(reason="ask_user")`
  - 外层 `try/except` 包裹路由 + 分发: 异常 → `ErrorEvent(message)` + `Done(aborted)`
  - `cfg.fast_mode=True` 时压制 `[engine]` log `TextChunk`
- 修改 `src/writer/engine/deps.py`:
  - `EngineDeps` Protocol 新增 `tool_registry: ToolRegistry` + `tool_runtime: ToolRuntime`
  - `_DefaultEngineDeps` 装配 `built_tool_registry()` + `ToolRuntime(project_root)`
  - `production_deps()` 看到 `settings.has_api_key=True` 时切换到 `CompositeRouter(RuleBasedIntentRouter, LlmIntentRouter)`,否则保持单 `RuleBasedIntentRouter`
- 修改 `src/writer/engine/events.py`:`DoneReason` 新增 `"tool_completed"` 字面量值(**轻量 BREAKING**,DoneReason 是 `Literal`,新增值会让下游 `match` 走穷尽性检查)。
- `S0` 路径(无 project_root)兼容:`ToolRuntime` 构造时 fallback 到 sentinel `Path("/__no_project__")` + 关闭 `safe_path` 越界检查,允许伏笔查询等"全局"工具在 S0 阶段可用。

## Capabilities

### New Capabilities

- `llm-provider`: 通过 Settings 驱动的 `get_llm()` factory,负责 ChatOpenAI 实例化与可 mock 性。覆盖: env var 缺失时抛明确错误;测试可注入 mock LLM。
- `intent-routing`: `IntentRouter` Protocol 下的两种实现 + 复合模式。覆盖: 规则版覆盖所有 `/` 前缀命令 + 自然语言 fallback 到"我能处理哪些命令"模板;LLM 版通过 LangChain `with_structured_output(AgentAction)` 解析自然语言;Composite 实现规则优先逻辑;LLM 异常/Pydantic schema 校验失败时 fallback 到规则版。
- `engine-loop`: 每轮 dispatch 状态机的所有分支活起来。覆盖: 五种 `AgentAction` 的完整事件流;ToolCall/ToolResult/Interrupt/ErrorEvent 实际 emit;`DoneReason` 增加 `"tool_completed"`;`EngineConfig.fast_mode` 压制 log chunks;EngineState 在 loop 内被构造并随 turn 推进。

### Modified Capabilities

无。现有 spec 目录为空,本次不修改任何已有 spec。

## Impact

- **受影响模块**:
  - 新增: `src/writer/llm/__init__.py`、`src/writer/llm/provider.py`
  - 新增: `src/writer/routing/llm_router.py`、`src/writer/routing/composite_router.py`
  - 修改: `src/writer/routing/__init__.py`(re-export)
  - 修改: `src/writer/engine/loop.py`(接活死分支 + 异常处理)
  - 修改: `src/writer/engine/deps.py`(Protocol 扩展 + production_deps 智能切换)
  - 修改: `src/writer/engine/events.py`(新增 DoneReason 字面量)
  - 修改: `src/writer/engine/config.py`(`fast_mode` 默认 `False` 保持向后兼容)
  - 修改: `src/writer/tools/runtime.py`(`ToolRuntime` 支持 sentinel project_root)
- **受影响测试**:
  - 现有 40 个测试中:
    - `test_engine_yields_done_for_tool` 需更新: 新增 `ToolCall` + `ToolResult` 事件断言,`Done.reason` 由 `"tool_pending"` 改为 `"tool_completed"`
    - 其他 39 个不动
  - 新增测试(mock `ChatOpenAI` + 注入 `EngineDeps`):
    - `test_get_llm_returns_chat_openai_with_settings` + `test_get_llm_missing_api_key_raises`
    - `test_llm_router_returns_structured_action` + `test_llm_router_falls_back_on_validation_error`
    - `test_composite_router_uses_rule_first_for_slash_commands`
    - `test_composite_router_invokes_llm_for_natural_language`
    - `test_production_deps_uses_llm_router_when_api_key_set`
    - `test_production_deps_uses_rule_router_when_no_api_key`
    - `test_engine_calls_tool_registry_on_call_tool_action`(覆盖 `tool_completed` 路径)
    - `test_engine_emits_error_event_on_router_failure`
    - `test_engine_emits_interrupt_for_ask_user_action`
    - `test_engine_fast_mode_suppresses_engine_log_chunks`
- **依赖**: 已经在 `pyproject.toml`,无需新增。`langchain-openai` / `pydantic` 已有。
- **BREAKING**: `DoneReason` 字面量集合扩了一员 `"tool_completed"`。当前代码无 `match ... case` 穷尽性使用,影响面主要是文档对齐与下游匹配分支需要补 case。