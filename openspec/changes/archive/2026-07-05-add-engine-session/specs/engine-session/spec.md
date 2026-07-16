## ADDED Requirements

### Requirement: EngineSession fixes session identity across turns

The system SHALL provide `EngineSession` in `src/writer/session/engine_session.py` that owns a single `session_id` (UUID) generated at construction and reused across every turn in a REPL session.

#### Scenario: Same session_id across turns
- **WHEN** a REPL driver constructs one `EngineSession` at startup and runs `run_engine(ctx, session.deps)` for 5 turns in a row
- **THEN** every `EngineContext` passed to `run_engine` MUST carry the same `session_id`
- **AND** the session_id MUST NOT change between turns

#### Scenario: session_id is a UUID
- **WHEN** `EngineSession()` is constructed with no arguments
- **THEN** `session.session_id` MUST be a valid `uuid.UUID` instance

#### Scenario: started_at captured at construction
- **WHEN** `EngineSession()` is constructed at time T
- **THEN** `session.started_at` MUST be a `datetime` whose value equals T (within ±1s tolerance)

### Requirement: EngineSession holds mutable cross-turn state

The system SHALL provide mutable fields on `EngineSession` for: `project_root`, `project_state`, `deps`, `turns`, `pending_interrupt`. Mutations are explicit (no hidden side effects).

#### Scenario: project_root defaults to None
- **WHEN** a fresh `EngineSession()` is created
- **THEN** `session.project_root` MUST be `None`

#### Scenario: project_state is the placeholder string
- **WHEN** a fresh `EngineSession()` is created
- **THEN** `session.project_state` MUST equal the string `"S0"` (placeholder until `detect_state()` lands later)

#### Scenario: turns starts empty
- **WHEN** a fresh `EngineSession()` is created
- **THEN** `session.turns` MUST be an empty `list`

#### Scenario: pending_interrupt starts None
- **WHEN** a fresh `EngineSession()` is created
- **THEN** `session.pending_interrupt` MUST be `None`

### Requirement: EngineSession builds deps once at construction

The system SHALL have `EngineSession` call `production_deps()` exactly once at construction time and store the result on `session.deps`.

#### Scenario: deps built at construction
- **WHEN** `EngineSession()` is constructed
- **THEN** `session.deps` MUST be a valid `EngineDeps` instance (satisfies `isinstance(deps, EngineDeps)`)

#### Scenario: deps not rebuilt per turn
- **WHEN** the same `EngineSession` is used for 3 turns in a row
- **THEN** the object identity of `session.deps` MUST be the same for all 3 turns (no per-turn rebuild)

### Requirement: EngineSession rebuilds tool_runtime when project_root changes

The system SHALL provide a `set_project_root(new_root)` method on `EngineSession` that updates `project_root` and rebuilds `deps.tool_runtime` while preserving the router / story_consultant / tool_registry fields.

#### Scenario: set_project_root updates state
- **WHEN** `session.set_project_root(Path("/tmp/my-novel"))` is called
- **THEN** `session.project_root` MUST equal `Path("/tmp/my-novel")`
- **AND** `session.deps.tool_runtime.project_root` MUST equal `Path("/tmp/my-novel").resolve()`

#### Scenario: set_project_root preserves router
- **WHEN** `session.set_project_root(new_root)` is called
- **THEN** `session.deps.router` MUST be the same object as before the call (router preserved)

#### Scenario: set_project_root to None uses sentinel
- **WHEN** `session.set_project_root(None)` is called
- **THEN** `session.deps.tool_runtime.project_root` MUST equal the sentinel `Path("/__no_project__").resolve()`

#### Scenario: set_project_root with same path is no-op
- **WHEN** `session.set_project_root(current_root)` is called with the same path
- **THEN** `session.deps` MUST be the same object as before the call (no rebuild)

### Requirement: EngineSession records each turn via TurnRecord

The system SHALL provide a `TurnRecord` dataclass `(turn_index: int, user_input: str, done_reason: DoneReason, timestamp: datetime)` and append one entry per turn.

#### Scenario: turn record appended after Done
- **WHEN** `session.record_turn(user_input="查 F003", done_reason="tool_completed")` is called
- **THEN** `session.turns` MUST contain exactly one `TurnRecord`
- **AND** the record's `turn_index` MUST be 0
- **AND** the record's `user_input` MUST equal `"查 F003"`
- **AND** the record's `done_reason` MUST equal `"tool_completed"`

#### Scenario: turn_index increments
- **WHEN** `session.record_turn(...)` is called three times in sequence
- **THEN** `session.turns[0].turn_index == 0`, `session.turns[1].turn_index == 1`, `session.turns[2].turn_index == 2`

#### Scenario: turns is append-only
- **WHEN** the REPL driver accesses `session.turns`
- **THEN** it MUST NOT need to manually maintain index counters; `record_turn` handles incrementing internally

### Requirement: EngineSession tracks pending Interrupt across turns

The system SHALL store an `Interrupt` event on `session.pending_interrupt` when the engine yields one, and clear it after the next turn's `Done` event.

#### Scenario: Interrupt sets pending
- **WHEN** the engine yields an `Interrupt(prompt="你想修改哪一段？")` event
- **THEN** the REPL driver MUST call `session.set_pending_interrupt(event)`
- **AND** `session.pending_interrupt` MUST be the `Interrupt` instance

#### Scenario: Done clears pending
- **WHEN** the engine yields a `Done` event in the same turn after the Interrupt
- **THEN** the REPL driver MUST call `session.clear_pending_interrupt()`
- **AND** `session.pending_interrupt` MUST be `None`

#### Scenario: pending persists until consumed
- **WHEN** `session.set_pending_interrupt(interrupt)` is called and no subsequent `clear_pending_interrupt` is invoked
- **THEN** `session.pending_interrupt` MUST remain set across multiple `record_turn` calls

### Requirement: REPL composes pending prompt with next user input

The system SHALL provide a `_compose_pending_input(original: str, pending: Interrupt) -> str` helper in `src/writer/cli/main.py` that prepends the pending question with a visible marker before the user's answer.

#### Scenario: pending text prompt composed
- **WHEN** `_compose_pending_input("修第2段", Interrupt(type="text", prompt="你想修改哪一段？"))` is called
- **THEN** the returned string MUST start with `"[pending] 你想修改哪一段？"`
- **AND** it MUST contain the user's input `"修第2段"` after a `[answer]` marker

#### Scenario: no pending returns original input
- **WHEN** `_compose_pending_input("查 F003", None)` is called
- **THEN** the returned string MUST equal `"查 F003"` (no modification)

### Requirement: REPL owns one EngineSession for its lifetime

The system SHALL have `run_repl()` construct exactly one `EngineSession` at the start of the loop and pass it to `_run_engine(text, session)` for every non-framework command.

#### Scenario: single session across REPL turns
- **WHEN** the REPL processes 4 non-framework inputs in sequence
- **THEN** all 4 invocations of `_run_engine` MUST receive the same `EngineSession` instance

#### Scenario: framework commands do not create session
- **WHEN** the user types `/退出` / `/帮助` / `/状态`
- **THEN** the REPL handles them inline without invoking `_run_engine`
- **AND** no `TurnRecord` is appended for framework commands

### Requirement: EngineSession package public surface

The system SHALL expose `EngineSession` and `TurnRecord` via `from writer.session import EngineSession, TurnRecord`.

#### Scenario: import works without side effects
- **WHEN** a consumer runs `from writer.session import EngineSession, TurnRecord`
- **THEN** the import MUST succeed without LLM instantiation or filesystem side effects