# Capability: engine-loop (delta)

## MODIFIED Requirements

### Requirement: Engine Loop dispatches all five AgentAction kinds

The `run_engine` async generator MUST handle the new `kind="agent"` case in addition to the existing `kind="command"` dispatch. The `kind` field on `AgentAction` (added per `fea-agent-mirror/specs/intent-routing`) determines which dispatch path is taken.

#### Scenario: agent kind dispatches to StoryAgent LLM call
- **WHEN** `deps.route()` returns `AgentAction(kind="agent", target_agent="history", args="我想写穿越到唐朝的程序员", action_type="answer_directly")`
- **THEN** the engine MUST look up the agent via `deps.agent_registry.require("history")` (raises `AgentRegistryError` if missing — see error scenario below)
- **AND** the engine MUST construct an LLM call whose system prompt is the agent's `body` (combined with the current `CONSULTANT_IDENTITY_*` / `AGENT_IDENTITY_*` template for the agent's `genre`)
- **AND** the engine MUST yield `TextChunk` events containing the LLM's streamed output
- **AND** the engine MUST yield `Done(reason="answered", payload={"agent": "history", "answer": <full LLM output>})` at the end

#### Scenario: agent kind for unknown agent raises AgentRegistryError
- **WHEN** `deps.route()` returns `AgentAction(kind="agent", target_agent="nonexistent", ...)` and `deps.agent_registry.require("nonexistent")` raises `AgentRegistryError`
- **THEN** the engine MUST catch `AgentRegistryError` (parallel to existing `ToolError` handling) and yield `ErrorEvent(message=<stringified AgentRegistryError>)`
- **AND** the engine MUST yield `Done(reason="aborted", payload={"error": <message>, "command": "nonexistent"})`
- **AND** the exception MUST NOT propagate out of `run_engine` to the consumer

#### Scenario: command kind unchanged
- **WHEN** `deps.route()` returns `AgentAction(kind="command", command="/大纲", ...)` (the existing default)
- **THEN** the engine MUST take the existing pre-change dispatch path (unchanged from `openspec/specs/engine-loop/spec.md` baseline)

### Requirement: Done payload for agent-dispatched turns

For `Done(reason="answered")` events that originated from an `AgentAction(kind="agent")`, the payload MUST include an `agent: str` field whose value equals `action.target_agent`. For `kind="command"` answered turns, the payload MUST NOT include an `agent` field (preserves back-compat).

#### Scenario: Payload contains agent name
- **WHEN** a turn is dispatched via `AgentAction(kind="agent", target_agent="history", action_type="answer_directly")`
- **THEN** the resulting `Done(reason="answered", payload=...)` MUST contain the key `"agent": "history"`
- **AND** the CLI renderer MUST be able to read `payload["agent"]` to display "由 history agent 回答"

#### Scenario: Payload unchanged for command-dispatched turns
- **WHEN** a turn is dispatched via `AgentAction(kind="command", command="/大纲", action_type="run_command")` and then converted to `Done(reason="answered", ...)` (the `/大纲` answered branch)
- **THEN** the payload MUST NOT contain an `agent` key
- **AND** MUST be `model_dump()`-equal to the pre-change payload shape
