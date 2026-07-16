# Capability: engine-loop (delta for real-writing-pipeline)

## Purpose

This delta modifies the `engine-loop` capability to: (1) recognize the new `workflow_completed` DoneReason and the new `WorkflowResult` contract for `EngineDeps.run_workflow`; (2) retire `workflow_pending` once all workflows are real.

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

#### Scenario: start_workflow path dispatches on WorkflowResult.status
- **WHEN** `deps.route()` returns `AgentAction(action_type="start_workflow", workflow="write_chapter")` and `deps.run_workflow("write_chapter", ctx)` returns `WorkflowResult(status="completed", chunks=(...), artifacts={"draft_path": Path("manuscript/ch1.md")}, metrics={"score": 8})`
- **THEN** the engine MUST yield each chunk from `result.chunks` as a `TextChunk`
- **AND** the engine MUST yield `Done(reason="workflow_completed", payload={"workflow": "write_chapter", "artifacts": {"draft_path": "manuscript/ch1.md"}, "metrics": {"score": 8}})`

#### Scenario: start_workflow with status=failed becomes aborted
- **WHEN** `deps.run_workflow(name, ctx)` returns `WorkflowResult(status="failed", metrics={"error": "..."})`
- **THEN** the engine MUST yield `Done(reason="aborted", payload={"workflow": name, "error": "..."})` and MUST NOT emit `workflow_completed`

#### Scenario: start_workflow with status=pending is deprecated
- **WHEN** `deps.run_workflow(name, ctx)` returns `WorkflowResult(status="pending", chunks=("partial",))`
- **THEN** the engine MUST yield each pending chunk as a `TextChunk`
- **AND** the engine MUST yield a deprecation `TextChunk` whose text starts with `"[engine] workflow_pending 已废弃"` (PR1 only; removed in PR3)
- **AND** the engine MUST yield `Done(reason="workflow_pending", payload={"workflow": name})` (PR1 only)

#### Scenario: ask_user path emits Interrupt
- **WHEN** `deps.route()` returns `AgentAction(action_type="ask_user", user_prompt="你想修改哪一段？")`
- **THEN** the engine MUST yield `Interrupt(type="text", prompt="你想修改哪一段？", options=None)`
- **AND** the engine MUST yield `Done(reason="ask_user", payload={"prompt": "你想修改哪一段？"})`

### Requirement: DoneReason includes tool_completed

The `DoneReason` Literal in `writer.engine.events` MUST include the values `"tool_completed"` and `"workflow_completed"`. The full set after PR1 is:

```text
answered | command_pending | tool_pending | workflow_pending | ask_user | aborted | tool_completed | workflow_completed
```

After PR3 the set is:

```text
answered | command_pending | tool_pending | ask_user | aborted | tool_completed | workflow_completed
```

`workflow_pending` is deprecated in PR1 and removed in PR3.

#### Scenario: Literal values are exported
- **WHEN** a consumer runs `from writer.engine.events import DoneReason` after PR1 is applied
- **THEN** `DoneReason` MUST be a Literal whose valid string values include `"tool_completed"` AND `"workflow_completed"`

#### Scenario: workflow_pending is rejected by mypy after PR3
- **WHEN** code constructs `Done(reason="workflow_pending", ...)` after PR3 is applied
- **THEN** mypy MUST report a Literal-mismatch error on the `reason=` argument
