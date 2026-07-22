# intent-routing Specification (delta)

## ADDED Requirements

### Requirement: RuleBasedIntentRouter routes /骨架 to skeleton_chapters workflow

`RuleBasedIntentRouter.route("/骨架 ...")` MUST return `AgentAction(action_type="start_workflow", command="/骨架", role="story_agent", workflow="skeleton_chapters", arguments={"raw": text})`. The branch MUST be placed adjacent to `/创作` / `/审核` branches in the source file (per `intent_router.py:101-116`).

PR1 only adds the routing branch. `rewrite` / `continue_` / `view` flag handling is NOT required at the router layer — those flags are parsed downstream by `writer.workflows.params.extract_skeleton_args` and honored in `skeleton_chapters.run` (PR1.5 / PR2).

#### Scenario: /骨架 full-mode routes to skeleton_chapters
- **WHEN** `RuleBasedIntentRouter().route("/骨架", _project_state="S4")` is called
- **THEN** the returned `AgentAction.workflow` MUST be `"skeleton_chapters"`
- **AND** `action_type` MUST be `"start_workflow"`
- **AND** `arguments["raw"]` MUST equal `"/骨架"`

#### Scenario: /骨架 volume-mode routes to skeleton_chapters
- **WHEN** `RuleBasedIntentRouter().route("/骨架 卷二", _project_state="S4")` is called
- **THEN** the returned `AgentAction.workflow` MUST be `"skeleton_chapters"`
- **AND** `arguments["raw"]` MUST equal `"/骨架 卷二"`

#### Scenario: /骨架 range-mode routes to skeleton_chapters
- **WHEN** `RuleBasedIntentRouter().route("/骨架 1.1-1.20", _project_state="S4")` is called
- **THEN** the returned `AgentAction.workflow` MUST be `"skeleton_chapters"`
- **AND** `arguments["raw"]` MUST equal `"/骨架 1.1-1.20"`

### Requirement: fallback answer text lists /骨架 among supported commands

The `answer_directly` fallback branch (per `intent_router.py:130-136`) MUST include `/骨架` in the comma-separated command list, alongside `/init`, `/大纲`, `/目录`, `/人物`, `/创作`, `/审核`.

#### Scenario: fallback text mentions /骨架
- **WHEN** `RuleBasedIntentRouter().route("random prose", _project_state="S4")` is called
- **THEN** the returned `AgentAction.answer` MUST contain the substring "/骨架"
- **AND** MUST contain "/大纲", "/目录", "/人物" (existing commands preserved)

### Requirement: LlmIntentRouter requires no changes for /骨架

`LlmIntentRouter` MUST NOT require any source code changes to support `/骨架`. The `CompositeRouter` primary (rule-based) branch catches any `/`-prefixed input via `looks_like_command` (per `intent_router.py:148-153`), so the LLM fallback never sees `/骨架` inputs as candidates for free-form agent dispatch.

#### Scenario: LlmIntentRouter source unchanged
- **WHEN** PR1 applies
- **THEN** `git diff src/writer/routing/llm_router.py` MUST be empty
- **AND** `COMMAND_AGENT_TEMPLATE` (per `prompts/router.py`) MUST NOT mention `/骨架`