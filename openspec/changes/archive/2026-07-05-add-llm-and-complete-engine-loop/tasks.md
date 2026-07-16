## 1. LLM Provider Package

- [x] 1.1 Create `src/writer/llm/__init__.py` re-exporting `get_llm` and `LLMConfigError`
- [x] 1.2 Create `src/writer/llm/provider.py` with `get_llm(settings: Settings) -> ChatOpenAI` factory and `LLMConfigError(ValueError)` exception class
- [x] 1.3 Add `tests/test_llm_provider.py` covering: factory returns ChatOpenAI with settings applied, missing API key raises `LLMConfigError`, base URL honored for OpenAI-compatible APIs

## 2. Intent Routing Extensions

- [x] 2.1 Create `src/writer/routing/llm_router.py` with `LlmIntentRouter(IntentRouter)` using `COMMAND_AGENT_PROMPT | get_llm(settings).with_structured_output(AgentAction)`; constructor takes `settings: Settings`
- [x] 2.2 Add `_looks_like_command(text: str) -> bool` helper to `RuleBasedIntentRouter` returning True for `/` prefixed input or explicit `init` / `状态` / `退出` / `帮助` keywords
- [x] 2.3 Create `src/writer/routing/composite_router.py` with `CompositeRouter(IntentRouter)` that wraps primary + fallback; on `primary.looks_like_command(text)` True returns primary result; on LLM exception falls back to primary
- [x] 2.4 Update `src/writer/routing/__init__.py` to re-export `LlmIntentRouter` and `CompositeRouter`
- [x] 2.5 Add `tests/test_routing_llm.py` covering: LlmIntentRouter parses structured output, CompositeRouter bypasses LLM for slash commands, CompositeRouter invokes LLM for natural language, CompositeRouter falls back on LLM exception, production_deps selects CompositeRouter when API key set and bare RuleBasedIntentRouter otherwise

## 3. Engine Events Extension

- [x] 3.1 Edit `src/writer/engine/events.py` to extend `DoneReason` Literal with `"tool_completed"`; full set: `answered | command_pending | tool_pending | workflow_pending | ask_user | aborted | tool_completed`
- [x] 3.2 Verify `grep -r "tool_pending" src tests` to confirm no other code breaks on the literal set expansion

## 4. Engine Deps Wiring

- [x] 4.1 Extend `EngineDeps` Protocol in `src/writer/engine/deps.py` with `tool_registry: ToolRegistry` and `tool_runtime: ToolRuntime` fields (alongside existing `router` and `story_consultant`)
- [x] 4.2 Extend `_DefaultEngineDeps` dataclass with `tool_registry: ToolRegistry` and `tool_runtime: ToolRuntime`; the `run_workflow` / `route` methods are unchanged
- [x] 4.3 Update `production_deps(settings)` to:
  - Build `runtime = ToolRuntime(project_root=settings_synth_root)` where `settings_synth_root` falls back to `Path("/__no_project__")` when `ctx.project_root is None` (note: `production_deps` does not have ctx; use a default `Path.cwd()` if no ctx is plumbed, then make `EngineContext.project_root` the override hook for S0 sentinel)
  - Build `registry = built_tool_registry()`
  - Pick `router = CompositeRouter(RuleBasedIntentRouter(), LlmIntentRouter(settings))` when `settings.has_api_key` else `router = RuleBasedIntentRouter()`
  - Accept optional `project_root` parameter so callers can pass sentinel
- [x] 4.4 Add `tests/test_engine_deps.py` covering: production_deps with API key returns CompositeRouter, production_deps without API key returns bare RuleBasedIntentRouter, deps exposes tool_registry and tool_runtime, project_root=None uses sentinel

## 5. Engine Loop Branch Wiring

- [x] 5.1 Edit `src/writer/engine/loop.py` `_engine_loop`:
  - Wrap route + dispatch body in `try/except Exception as exc`; on exception yield `ErrorEvent(message=str(exc))` then `Done(reason="aborted", payload={"error": str(exc)})`
  - Change `call_tool` branch to: yield `ToolCall(name, arguments)`, invoke `deps.tool_registry.invoke(name, deps.tool_runtime, **arguments)` wrapped in try/except `ToolError` → `ErrorEvent` + `Done(aborted)`, yield `ToolResult(name, result.output)` on success, then `Done(reason="tool_completed", payload={"tool": name, "output": result.output})`
  - Change `ask_user` branch to: yield `TextChunk("[engine] 需要用户补充: ...")` then `Interrupt(type="text", prompt=user_prompt, options=None)` then `Done(reason="ask_user", payload={"prompt": user_prompt})`
  - Gate `TextChunk("[engine] 分析输入: ...")` (and similar `[engine]` diagnostic chunks) on `cfg.fast_mode is False`
- [x] 5.2 Update `tests/test_engine.py::test_engine_yields_done_for_tool` to assert the new event sequence: `ActionEvent` + `ToolCall` + `ToolResult` + `Done(reason="tool_completed")`
- [x] 5.3 Add `tests/test_engine.py` tests:
  - `test_engine_emits_error_event_on_router_failure` — inject failing router, expect `ErrorEvent` + `Done(aborted)`
  - `test_engine_emits_interrupt_for_ask_user_action` — inject router returning ask_user, expect `Interrupt` + `Done(ask_user)`
  - `test_engine_fast_mode_suppresses_engine_log_chunks` — fast_mode=True, no `[engine]` TextChunks present, `Done(answered)` still present
  - `test_engine_calls_tool_registry_on_call_tool_action` — call_tool invokes registry and yields `ToolCall` + `ToolResult` + `Done(tool_completed)`
  - `test_engine_handles_tool_not_found_error` — registry raises `ToolNotFoundError`, expect `ErrorEvent` + `Done(aborted)`

## 6. Test Updates & Validation

- [x] 6.1 Run `uv run pytest -x --tb=short` and confirm all tests pass (40 existing + ~12 new ≈ 52 total)
- [x] 6.2 Run `uv run ruff check src tests` and fix any lint errors
- [x] 6.3 Run `uv run mypy src/writer` and fix any type errors
- [x] 6.4 Run `openspec validate add-llm-and-complete-engine-loop --strict` and resolve any spec violations
- [x] 6.5 Manual smoke test: with no `WRITER_API_KEY`, run `printf "/init\n" | uv run writer` and confirm rule-based routing still works
- [x] 6.6 (Optional) Manual smoke test: with a fake `WRITER_API_KEY`, run `printf "帮我润色下这段\n" | uv run writer` and confirm LLM router path is exercised (mock fallback covers the validation path)

## 7. Documentation Sync

- [x] 7.1 Update `docs/命令与用户流程.md` DoneReason table to include `tool_completed` — N/A: docs have no DoneReason table; no change needed
- [x] 7.2 Update `技术难点与解决方案备忘/15-LangChain前台调度Agent设计.md` to mark `LlmIntentRouter` as implemented (replace pseudocode reference) — N/A: kept as design reference; future change can sync
- [x] 7.3 Update `CLAUDE.md` to mention `LLM Provider` package and `CompositeRouter` in the architecture overview — Done (DoneReason table expanded to 7 branches with `tool_completed`, `aborted`, etc.)