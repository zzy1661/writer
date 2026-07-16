## MODIFIED Requirements

### Requirement: Engine Loop dispatches all five AgentAction types

The `run_engine` async generator MUST handle every `action_type` in the `ActionType` Literal and emit a terminal `Done` event for each.

#### Scenario: answer_directly path
- **WHEN** `deps.route()` returns `AgentAction(action_type="answer_directly", answer="...")`
- **THEN** the engine MUST yield a `TextChunk` containing the answer followed by `Done(reason="answered", payload={"answer": ...})`

#### Scenario: run_command path (non-大纲)
- **WHEN** `deps.route()` returns `AgentAction(action_type="run_command", command="/init")`
- **THEN** the engine MUST yield `Done(reason="command_pending", payload={"command": "/init"})`

#### Scenario: call_tool path now invokes registry
- **WHEN** `deps.route()` returns `AgentAction(action_type="call_tool", tool_name="foreshadow_search", arguments={"id": "F003"})`
- **THEN** the engine MUST yield `ToolCall(name="foreshadow_search", arguments={"id": "F003"})`
- **AND** the engine MUST invoke `deps.tool_registry.invoke("foreshadow_search", deps.tool_runtime, id="F003")` exactly once
- **AND** the engine MUST yield `ToolResult(name="foreshadow_search", output=<invocation result>)`
- **AND** the engine MUST yield `Done(reason="tool_completed", payload={"tool": "foreshadow_search", "output": ...})`

#### Scenario: call_tool path with multiple filter arguments
- **WHEN** `deps.route()` returns `AgentAction(action_type="call_tool", tool_name="foreshadow_search", arguments={"tags": ["玉簪"], "status": "laid"})`
- **THEN** the engine MUST invoke `deps.tool_registry.invoke("foreshadow_search", deps.tool_runtime, tags=["玉簪"], status="laid")` exactly once
- **AND** the engine MUST yield `ToolResult(name="foreshadow_search", output=<invocation result>)` and `Done(reason="tool_completed", payload={"tool": "foreshadow_search", "output": ...})`

#### Scenario: start_workflow path
- **WHEN** `deps.route()` returns `AgentAction(action_type="start_workflow", workflow="write_chapter")`
- **THEN** the engine MUST dispatch to the registered workflow stub and yield its chunks followed by `Done(reason="workflow_pending", payload={"workflow": "write_chapter"})`

#### Scenario: ask_user path emits Interrupt
- **WHEN** `deps.route()` returns `AgentAction(action_type="ask_user", user_prompt="你想修改哪一段？")`
- **THEN** the engine MUST yield `Interrupt(type="text", prompt="你想修改哪一段？", options=None)`
- **AND** the engine MUST yield `Done(reason="ask_user", payload={"prompt": "你想修改哪一段？"})`

### Requirement: Engine emits ErrorEvent on exceptions

The `_engine_loop` async generator MUST wrap route + dispatch in a try/except block so that any uncaught exception yields an `ErrorEvent` followed by `Done(reason="aborted")`.

#### Scenario: Router raises
- **WHEN** `deps.route()` raises an exception
- **THEN** the engine MUST yield `ErrorEvent(message=<stringified exception>)`
- **AND** the engine MUST yield `Done(reason="aborted", payload={"error": <message>})`
- **AND** the exception MUST NOT propagate out of `run_engine` to the consumer

#### Scenario: Tool raises ToolError
- **WHEN** `deps.tool_registry.invoke(...)` raises `ToolError` (or subclass `ToolNotFoundError`, `ToolDeniedError`, `ToolOutputTooLargeError`)
- **THEN** the engine MUST yield `ErrorEvent(message=<stringified ToolError>)`
- **AND** the engine MUST yield `Done(reason="aborted", payload={"error": <message>})`

#### Scenario: Workflow raises
- **WHEN** `deps.run_workflow(...)` raises an exception
- **THEN** the engine MUST yield `ErrorEvent` + `Done(reason="aborted")`
- **AND** the exception MUST NOT propagate out

### Requirement: EngineConfig.fast_mode suppresses engine log chunks

When `cfg.fast_mode` is True, the engine MUST NOT yield `TextChunk` events whose text starts with `"[engine]"` (diagnostic chunks); business events (`ActionEvent`, `ToolCall`, `ToolResult`, `Interrupt`, `Done`, `ErrorEvent`) MUST still be emitted.

#### Scenario: fast_mode on
- **WHEN** `run_engine(ctx, deps, config=EngineConfig(session_id="x", fast_mode=True))` runs an answer_directly turn
- **THEN** no `TextChunk` starting with `"[engine]"` MUST appear in the event stream
- **AND** the `Done(reason="answered")` event MUST still appear

#### Scenario: fast_mode off (default)
- **WHEN** `run_engine(...)` runs without an explicit `config` (defaults applied)
- **THEN** `TextChunk("[engine] 分析输入: ...")` MUST appear in the event stream

### Requirement: Engine supports S0 path without project_root

When `EngineContext.project_root is None`, the engine MUST still be able to invoke tools that do not require file paths (e.g., `foreshadow_search`, `chapter_locate`, `wordcount`) and MUST yield `ErrorEvent` + `Done(aborted)` for tools that do.

#### Scenario: S0 tool call to path-free tool
- **WHEN** `ctx.project_root is None` and the action targets `foreshadow_search`
- **THEN** the engine MUST invoke the tool via a fallback `ToolRuntime` and yield `ToolCall` / `ToolResult` / `Done(reason="tool_completed")`
- **AND** if the tool itself rejects `project_root=None`, the tool MUST return a `ToolResult` with `metadata.error="no_project_root"` (not raise) and the engine MUST surface that as a normal `ToolResult`

#### Scenario: S0 tool call to file tool
- **WHEN** `ctx.project_root is None` and the action targets `safe_read_file`
- **THEN** the engine MUST yield `ErrorEvent` describing the missing project root
- **AND** the engine MUST yield `Done(reason="aborted")`

### Requirement: DoneReason includes tool_completed

The `DoneReason` Literal in `writer.engine.events` MUST include the value `"tool_completed"`. The full set is:

```text
answered | command_pending | tool_pending | workflow_pending | ask_user | aborted | tool_completed
```

#### Scenario: Literal value is exported
- **WHEN** a consumer runs `from writer.engine.events import DoneReason`
- **THEN** `DoneReason` MUST be a Literal type whose valid string values include `"tool_completed"`
