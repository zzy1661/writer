## 1. Session Package Skeleton

- [x] 1.1 Create `src/writer/session/__init__.py` re-exporting `EngineSession` and `TurnRecord`
- [x] 1.2 Create `src/writer/session/engine_session.py` with `TurnRecord` dataclass `(turn_index, user_input, done_reason, timestamp)` and `EngineSession` dataclass with all 7 fields + `__post_init__` that calls `production_deps()`
- [x] 1.3 Add `EngineSession.set_project_root(new_root)` method that swaps only `tool_runtime` while preserving router / story_consultant / tool_registry (per D2)

## 2. EngineSession State Methods

- [x] 2.1 Add `EngineSession.record_turn(user_input, done_reason)` method that appends a `TurnRecord` with auto-incrementing `turn_index`
- [x] 2.2 Add `EngineSession.set_pending_interrupt(interrupt)` and `clear_pending_interrupt()` methods
- [x] 2.3 Add module-level `_compose_pending_input(original: str, pending: Interrupt | None) -> str` helper (initially in `engine_session.py`, will be re-exported to cli)

## 3. REPL Refactor

- [x] 3.1 Modify `src/writer/cli/main.py`:
  - `run_repl()` constructs one `EngineSession` at start of loop, passes it to `_run_engine(text, session)` for non-framework commands
  - `_run_engine(text, session)` reads `session.session_id` for `EngineContext` (no per-turn uuid)
  - At turn start, if `session.pending_interrupt` is set, compose `ctx.user_input` via `_compose_pending_input(original_text, session.pending_interrupt)`
  - In event loop: `Interrupt` event → `session.set_pending_interrupt(event)`; `Done` event → `session.record_turn(text, event.reason)` + `session.clear_pending_interrupt()`
- [x] 3.2 Keep `_run_engine(text, console)` single-arg wrapper as backward-compatible shim for tests by constructing a default `EngineSession()` internally — Applied as: tests updated to construct an `EngineSession` and pass it to `handle_repl_input`.

## 4. Tests

- [x] 4.1 Create `tests/test_engine_session.py` with:
  - `test_session_fixes_session_id_across_turns` — record 3 turns, all share same `session_id`
  - `test_session_records_each_turn` — `record_turn` appends TurnRecord with correct fields
  - `test_session_pending_interrupt_cleared_after_done` — set + clear lifecycle
  - `test_session_pending_interrupt_composes_with_next_user_input` — `_compose_pending_input` returns expected merged string
  - `test_session_deps_built_once_at_construction` — `session.deps` object identity stable across turns
  - `test_session_tool_runtime_rebuilt_when_project_root_changes` — `set_project_root` swaps only tool_runtime, preserves router
  - `test_session_persists_project_root_across_turns` — after `set_project_root`, subsequent reads return same path
  - `test_session_project_state_is_placeholder_for_now` — defaults to `"S0"`
- [x] 4.2 Extend `tests/test_cli.py` with:
  - `test_repl_session_survives_across_lines` — multi-line input keeps single session_id (use mock session or capture console output)
  - `test_repl_pending_interrupt_visible_in_next_turn` — when engine yields Interrupt, next input is composed
  - `test_repl_exit_command_terminates_session` — `/退出` returns False from `handle_repl_input`

## 5. Validation

- [x] 5.1 Run `uv run pytest tests/ -q` and confirm 64 existing + ~11 new tests pass — 84 passed
- [x] 5.2 Run `uv run ruff check src tests` and fix any lint errors — clean
- [x] 5.3 Run `uv run mypy src/writer` and fix any type errors — clean
- [x] 5.4 Run `openspec validate add-engine-session --strict` and resolve any spec violations — valid
- [x] 5.5 Manual smoke: `printf "/init\n/init\n" | uv run writer` — both turns share session_id (visible in logs) — verified via `/状态\n/状态` showing same UUID
- [x] 5.6 Manual smoke: `printf "查 F003\n帮我润色下这段\n" | uv run writer` — turns accumulate in session — verified (call_tool + answer_directly across 2 turns, same session)

## 6. Documentation Sync

- [x] 6.1 Update `CLAUDE.md` "事件流与 Done 分支" section to mention EngineSession as the owner of session_id across turns — added "会话层" paragraph
- [x] 6.2 Update `CLAUDE.md` "包职责" table to add `session` row — done