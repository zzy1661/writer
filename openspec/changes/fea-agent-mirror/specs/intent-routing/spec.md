# Capability: intent-routing (delta)

## MODIFIED Requirements

### Requirement: AgentAction carries kind and target_agent

The `AgentAction` Pydantic model MUST add two new fields:

* `kind: Literal["command", "agent"]` — default `"command"` (preserves back-compat for all existing call sites)
* `target_agent: str | None` — default `None`; populated when `kind="agent"`

#### Scenario: Default AgentAction is a command
- **WHEN** any existing call site constructs `AgentAction(command="/大纲", args="...")` without specifying `kind`
- **THEN** the resulting `AgentAction` MUST have `kind="command"` and `target_agent=None`
- **AND** it MUST be `model_dump()`-equal to the pre-change shape (ignoring the new defaulted fields)

#### Scenario: Agent-targeted AgentAction
- **WHEN** the LLM picks an agent (see "LlmIntentRouter sees agent descriptions" requirement below)
- **THEN** the resulting `AgentAction` MUST have `kind="agent"`, `command=None`, and `target_agent=<agent name>`

### Requirement: LlmIntentRouter sees agent descriptions

When the `LlmIntentRouter` is constructed with an `agent_registry` (i.e. not in legacy no-registry mode), its system prompt MUST include a section listing each agent's `{name, description, genre}` (the `AgentRegistry.descriptions()` output). The section MUST appear after the slash-command list so the LLM first tries to match a slash command, then falls back to an agent.

#### Scenario: Agent descriptions appear in system prompt
- **WHEN** `LlmIntentRouter(agent_registry=registry_with_2_agents)` is constructed
- **THEN** the LLM system prompt used during `route()` MUST contain both agents' `name` and a truncated form of their `description`
- **AND** the agent section MUST appear AFTER the slash-command list (verified by string position)

#### Scenario: Legacy LlmIntentRouter mode has no agent section
- **WHEN** `LlmIntentRouter()` is constructed without `agent_registry`
- **THEN** the LLM system prompt MUST NOT contain any agent section
- **AND** `target_agent` in the structured-output schema MUST be a no-op (always `None`)

### Requirement: LlmIntentRouter structured output includes target_agent

The structured-output schema used by `LlmIntentRouter` (the Pydantic model that the LLM is asked to fill in) MUST add a `target_agent: str | None = None` field. When the LLM fills in `target_agent`, the router MUST emit `AgentAction(kind="agent", target_agent=<that value>, command=None, action_type=<existing>, args=...)`. When the LLM leaves `target_agent=None` and fills `command`, the existing behavior is preserved.

#### Scenario: LLM picks an agent
- **WHEN** the LLM returns `_RouterDecision(target_agent="history", command=None, action_type="answer_directly", ...)`
- **THEN** `LlmIntentRouter.route(...)` MUST return `AgentAction(kind="agent", target_agent="history", command=None, action_type="answer_directly", ...)`

#### Scenario: LLM picks a slash command (no agent)
- **WHEN** the LLM returns `_RouterDecision(target_agent=None, command="/大纲", action_type="run_command", ...)`
- **THEN** `LlmIntentRouter.route(...)` MUST return `AgentAction(kind="command", target_agent=None, command="/大纲", action_type="run_command", ...)` — equivalent to pre-change behavior

#### Scenario: LLM picks both command and target_agent
- **WHEN** the LLM returns `_RouterDecision(target_agent="history", command="/大纲", ...)` (invalid combination)
- **THEN** the router MUST prefer `target_agent` (kind="agent") and ignore `command`; a log WARNING MUST be emitted about the ambiguous input
- **OR** raise `ValueError` — the apply phase decides which strictness; the spec allows either as long as the outcome is unambiguous

### Requirement: production_deps wires agent_registry into the router

`production_deps()` MUST inject the resolved `agent_registry` into the LLM router construction path. The rule-based router does not need `agent_registry` (it operates on slash commands only).

#### Scenario: API key present
- **WHEN** `production_deps(settings_with_key, agent_registry=registry)` is called
- **THEN** `deps.router` MUST be a `CompositeRouter` whose LLM fallback was constructed with `agent_registry=registry`
- **AND** `deps.agent_registry` MUST be the same `registry`

#### Scenario: API key absent (rule-only mode)
- **WHEN** `production_deps(settings_without_key, agent_registry=registry)` is called
- **THEN** `deps.router` MUST be exactly a `RuleBasedIntentRouter` (the LLM router is not constructed)
- **AND** `deps.agent_registry` MUST still equal the passed `registry` (so future operations like agent-dispatch can still consult it)
