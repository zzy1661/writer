## ADDED Requirements

### Requirement: RuleBasedIntentRouter returns structured action

The system MUST continue to provide `RuleBasedIntentRouter` satisfying the `IntentRouter` Protocol; its behavior for existing command patterns MUST be preserved.

#### Scenario: Slash command routing
- **WHEN** `RuleBasedIntentRouter().route("/写 1.3", "S0")` is called
- **THEN** it MUST return an `AgentAction` with `action_type="start_workflow"`, `workflow="write_chapter"`, `role="story_consultant"`, `command="/写"`

#### Scenario: Foreshadow query routing
- **WHEN** `RuleBasedIntentRouter().route("查一下 F003", "S2")` is called
- **THEN** it MUST return an `AgentAction` with `action_type="call_tool"`, `tool_name="foreshadow_query"`, `arguments={"query": "查一下 F003"}`

#### Scenario: Free-form input falls back to answer
- **WHEN** `RuleBasedIntentRouter().route("帮我润色下这段", "S2")` is called
- **THEN** it MUST return an `AgentAction` with `action_type="answer_directly"` and an `answer` echoing the input

### Requirement: LlmIntentRouter uses structured output

The system SHALL provide `LlmIntentRouter(IntentRouter)` that uses LangChain `with_structured_output(AgentAction)` and a prompt instructing the model to convert natural-language input into an `AgentAction`.

#### Scenario: Natural language parsed to start_workflow
- **WHEN** the LLM receives the prompt "用户输入: 帮我写下一章" and returns a valid `AgentAction(action_type="start_workflow", workflow="write_chapter", role="story_consultant")`
- **THEN** `LlmIntentRouter().route("帮我写下一章", "S3")` MUST return that exact `AgentAction`

#### Scenario: Natural language parsed to call_tool
- **WHEN** the LLM returns `AgentAction(action_type="call_tool", tool_name="foreshadow_query", arguments={"query": "F003"})`
- **THEN** `LlmIntentRouter.route("查 F003 出现在哪", "S4")` MUST return that `AgentAction`

#### Scenario: Insufficient info returns ask_user
- **WHEN** the LLM returns `AgentAction(action_type="ask_user", user_prompt="你想修改哪一段？")`
- **THEN** `LlmIntentRouter.route(...)` MUST return that `AgentAction`

### Requirement: CompositeRouter applies rule-first logic

The system SHALL provide `CompositeRouter(IntentRouter)` that wraps a rule-based primary router and an LLM fallback router, invoking the LLM only when the rule router's predicate classifies input as non-command.

#### Scenario: Slash command bypasses LLM
- **WHEN** `CompositeRouter(primary=RuleBasedIntentRouter(), fallback=LlmIntentRouter(mocked_to_fail))` receives `"/init"`
- **THEN** the LLM MUST NOT be invoked (verified by the fallback mock's call count = 0)
- **AND** the returned action MUST equal `RuleBasedIntentRouter().route("/init", state)`

#### Scenario: Natural language invokes LLM
- **WHEN** `CompositeRouter` receives "帮我写下一章"
- **THEN** the LLM fallback MUST be invoked exactly once
- **AND** the returned action MUST equal the LLM's parsed `AgentAction`

#### Scenario: LLM failure falls back to rule
- **WHEN** `LlmIntentRouter` raises (Pydantic ValidationError, Timeout, HTTPError)
- **THEN** `CompositeRouter.route()` MUST catch the exception and return `RuleBasedIntentRouter().route(user_input, project_state)` instead

### Requirement: Production deps selects router by API key presence

The system MUST have `production_deps()` instantiate a `CompositeRouter` when `settings.has_api_key is True`, and a bare `RuleBasedIntentRouter` otherwise.

#### Scenario: API key present
- **WHEN** `production_deps(settings_with_key)` is called
- **THEN** `deps.router` MUST be a `CompositeRouter` whose primary is `RuleBasedIntentRouter` and whose fallback is `LlmIntentRouter`

#### Scenario: API key absent
- **WHEN** `production_deps(settings_without_key)` is called
- **THEN** `deps.router` MUST be exactly a `RuleBasedIntentRouter` (not wrapped in CompositeRouter)
- **AND** no LLM construction code path MUST be triggered

### Requirement: Router decisions are deterministic given fixed inputs

Both `RuleBasedIntentRouter.route()` and `CompositeRouter.route()` MUST be deterministic for the same `(user_input, project_state)` pair when the LLM is mocked to return a fixed answer.

#### Scenario: Repeated calls return same action
- **WHEN** `CompositeRouter(...).route("/init", "S0")` is called twice
- **THEN** both results MUST be equal `AgentAction` instances (by `model_dump()`)