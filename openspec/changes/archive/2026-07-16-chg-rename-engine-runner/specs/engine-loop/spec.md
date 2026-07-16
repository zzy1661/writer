## MODIFIED Requirements

### Requirement: Engine Loop dispatches all five AgentAction types

The `run_runner` async generator (renamed from `run_engine` in `src/writer/engine/loop.py`; the new compat shim is `src/writer/runner/loop.py`) MUST handle every `action_type` in the `ActionType` Literal and emit a terminal `Done` event for each.

#### Scenario: answer_directly path
- **WHEN** `deps.route()` returns `AgentAction(action_type="answer_directly", answer="...")`
- **THEN** the runner MUST yield a `TextChunk` containing the answer followed by `Done(reason="answered", payload={"answer": ...})`

#### Scenario: run_command path (non-大纲)
- **WHEN** `deps.route()` returns `AgentAction(action_type="run_command", command="/init")`
- **THEN** the runner MUST yield `Done(reason="command_pending", payload={"command": "/init"})`

#### Scenario: call_tool path now invokes registry
- **WHEN** `deps.route()` returns `AgentAction(action_type="call_tool", tool_name="foreshadow_search", arguments={"id": "F003"})`
- **THEN** the runner MUST yield `ToolCall(name="foreshadow_search", arguments={"id": "F003"})`
- **AND** the runner MUST invoke `deps.tool_registry.invoke("foreshadow_search", deps.tool_runtime, id="F003")` exactly once
- **AND** the runner MUST yield `ToolResult(name="foreshadow_search", output=<invocation result>)`
- **AND** the runner MUST yield `Done(reason="tool_completed", payload={"tool": "foreshadow_search", "output": ...})`

#### Scenario: call_tool path with multiple filter arguments
- **WHEN** `deps.route()` returns `AgentAction(action_type="call_tool", tool_name="foreshadow_search", arguments={"tags": ["玉簪"], "status": "laid"})`
- **THEN** the runner MUST invoke `deps.tool_registry.invoke("foreshadow_search", deps.tool_runtime, tags=["玉簪"], status="laid")` exactly once
- **AND** the runner MUST yield `ToolResult(name="foreshadow_search", output=<invocation result>)` and `Done(reason="tool_completed", payload={"tool": "foreshadow_search", "output": ...})`

#### Scenario: start_workflow path dispatches on WorkflowResult.status
- **WHEN** `deps.route()` returns `AgentAction(action_type="start_workflow", workflow="write_chapter")` and `deps.run_workflow("write_chapter", ctx)` returns `WorkflowResult(status="completed", chunks=(...), artifacts={"draft_path": Path("manuscript/ch1.md")}, metrics={"score": 8})`
- **THEN** the runner MUST yield each chunk from `result.chunks` as a `TextChunk`
- **AND** the runner MUST yield `Done(reason="workflow_completed", payload={"workflow": "write_chapter", "artifacts": {"draft_path": "manuscript/ch1.md"}, "metrics": {"score": 8}})`

#### Scenario: start_workflow with status=failed becomes aborted
- **WHEN** `deps.run_workflow(name, ctx)` returns `WorkflowResult(status="failed", metrics={"error": "..."})`
- **THEN** the runner MUST yield `Done(reason="aborted", payload={"workflow": name, "error": "..."})` and MUST NOT emit `workflow_completed`

#### Scenario: start_workflow with status=pending is deprecated
- **WHEN** `deps.run_workflow(name, ctx)` returns `WorkflowResult(status="pending", chunks=("partial",))`
- **THEN** the runner MUST yield each pending chunk as a `TextChunk`
- **AND** the runner MUST yield a deprecation `TextChunk` whose text starts with `"[engine] workflow_pending 已废弃"` (PR1 only; removed in PR3)
- **AND** the runner MUST yield `Done(reason="workflow_pending", payload={"workflow": name})` (PR1 only)

#### Scenario: ask_user path emits Interrupt
- **WHEN** `deps.route()` returns `AgentAction(action_type="ask_user", user_prompt="你想修改哪一段？")`
- **THEN** the runner MUST yield `Interrupt(type="text", prompt="你想修改哪一段？", options=None)`
- **AND** the runner MUST yield `Done(reason="ask_user", payload={"prompt": "你想修改哪一段？"})`

### Requirement: Engine emits ErrorEvent on exceptions

The `_engine_loop` async generator on `Runner` (formerly `Engine` in `src/writer/engine/engine.py`; the new class lives at `src/writer/runner/runner.py`) MUST wrap route + dispatch in a try/except block so that any uncaught exception yields an `ErrorEvent` followed by `Done(reason="aborted")`.

#### Scenario: Router raises
- **WHEN** `deps.route()` raises an exception
- **THEN** the runner MUST yield `ErrorEvent(message=<stringified exception>)`
- **AND** the runner MUST yield `Done(reason="aborted", payload={"error": <message>})`
- **AND** the exception MUST NOT propagate out of `run_runner` to the consumer

#### Scenario: Tool raises ToolError
- **WHEN** `deps.tool_registry.invoke(...)` raises `ToolError` (or subclass `ToolNotFoundError`, `ToolDeniedError`, `ToolOutputTooLargeError`)
- **THEN** the runner MUST yield `ErrorEvent(message=<stringified ToolError>)`
- **AND** the runner MUST yield `Done(reason="aborted", payload={"error": <message>})`

#### Scenario: Workflow raises
- **WHEN** `deps.run_workflow(...)` raises an exception
- **THEN** the runner MUST yield `ErrorEvent` + `Done(reason="aborted")`
- **AND** the exception MUST NOT propagate out

### Requirement: EngineConfig.fast_mode suppresses engine log chunks

When `cfg.fast_mode` is True, the runner MUST NOT yield `TextChunk` events whose text starts with `"[engine]"` (diagnostic chunks); business events (`ActionEvent`, `ToolCall`, `ToolResult`, `Interrupt`, `Done`, `ErrorEvent`) MUST still be emitted. The class is now `RunnerConfig` (formerly `EngineConfig`) and lives at `src/writer/runner/config.py`.

#### Scenario: fast_mode on
- **WHEN** `run_runner(ctx, deps, config=RunnerConfig(session_id="x", fast_mode=True))` runs an answer_directly turn
- **THEN** no `TextChunk` starting with `"[engine]"` MUST appear in the event stream
- **AND** the `Done(reason="answered")` event MUST still appear

#### Scenario: fast_mode off (default)
- **WHEN** `run_runner(...)` runs without an explicit `config` (defaults applied)
- **THEN** `TextChunk("[engine] 分析输入: ...")` MUST appear in the event stream

### Requirement: Engine supports S0 path without project_root

When `RunnerContext.project_root is None` (formerly `EngineContext.project_root`), the runner MUST still be able to invoke tools that do not require file paths (e.g., `foreshadow_search`, `chapter_locate`, `wordcount`) and MUST yield `ErrorEvent` + `Done(aborted)` for tools that do.

#### Scenario: S0 tool call to path-free tool
- **WHEN** `ctx.project_root is None` and the action targets `foreshadow_search`
- **THEN** the runner MUST invoke the tool via a fallback `ToolRuntime` and yield `ToolCall` / `ToolResult` / `Done(reason="tool_completed")`
- **AND** if the tool itself rejects `project_root=None`, the tool MUST return a `ToolResult` with `metadata.error="no_project_root"` (not raise) and the runner MUST surface that as a normal `ToolResult`

#### Scenario: S0 tool call to file tool
- **WHEN** `ctx.project_root is None` and the action targets `safe_read_file`
- **THEN** the runner MUST yield `ErrorEvent` describing the missing project root
- **AND** the runner MUST yield `Done(reason="aborted")`

### Requirement: DoneReason includes tool_completed

The `DoneReason` Literal in `writer.runner.events` (formerly `writer.engine.events`) MUST include the values `"tool_completed"` and `"workflow_completed"`. The full set after PR1 is:

```text
answered | command_pending | tool_pending | workflow_pending | ask_user | aborted | tool_completed | workflow_completed
```

After PR3 the set is:

```text
answered | command_pending | tool_pending | ask_user | aborted | tool_completed | workflow_completed
```

`workflow_pending` is deprecated in PR1 and removed in PR3.

#### Scenario: Literal values are exported
- **WHEN** a consumer runs `from writer.runner.events import DoneReason` after PR1 is applied
- **THEN** `DoneReason` MUST be a Literal whose valid string values include `"tool_completed"` AND `"workflow_completed"`

#### Scenario: workflow_pending is rejected by mypy after PR3
- **WHEN** code constructs `Done(reason="workflow_pending", ...)` after PR3 is applied
- **THEN** mypy MUST report a Literal-mismatch error on the `reason=` argument