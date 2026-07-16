## 1. New `src/writer/agents/` package skeleton

- [ ] 1.1 Create `src/writer/agents/__init__.py` (empty stub re-exporting `Agent`, `AgentRegistry`, `AgentRegistryError`, `built_agent_registry`, `builtin_agent_registry`, `discover_project_agents`, `discover_entry_point_agents`).
- [ ] 1.2 Create `src/writer/agents/protocol.py` with the `Agent` Protocol: `name: str` / `description: str` / `genre: str` / `body: str` / `tools_allowlist: tuple[str, ...]` (default `()`). Use `@runtime_checkable` (mirror `Skill` Protocol style).
- [ ] 1.3 Create `src/writer/agents/registry.py` with `AgentRegistryError(ValueError)`, `AgentRegistry(agents: list[Agent])` (last-write-wins on `name`, first-registration-wins within same scope), `.get(name) -> Agent | None`, `.require(name) -> Agent` (raises `AgentRegistryError`), `.all() -> list[Agent]`, `.descriptions() -> list[dict]` (returns `[{name, description, genre}]` for LLM dispatch).
- [ ] 1.4 Create `src/writer/agents/loader.py` with `parse_agent_file(path: Path) -> Agent` (YAML frontmatter + body via `yaml.safe_load` + `---` split). Raises `AgentRegistryError` on missing required keys (`name` / `description` / `genre`) or empty body.
- [ ] 1.5 Create `src/writer/agents/builtin_sources.py` with `BUILTIN_AGENT_SOURCES: tuple[tuple[str, str, str, str], ...]` mirroring `BUILTIN_SKILL_SOURCES` shape: `(name, mirror_filename, source_module, source_sha256, ...)`. Provide `builtin_agent_registry() -> AgentRegistry` (built-in only) and `built_agent_registry(project_root: Path | None = None) -> AgentRegistry` (built-in + project overrides + entry-point plugins). Add `discover_project_agents(root: Path) -> list[Agent]` and `discover_entry_point_agents() -> list[Agent]`.

## 2. Author 4 built-in agent `.md` files

- [ ] 2.1 Create `src/writer/agents/_shipped/other.md` (YAML frontmatter: `name: other`, `genre: other`, `description: "..."` 100-200 字符中文；body 源自 `CONSULTANT_IDENTITY_STORY`).
- [ ] 2.2 Create `src/writer/agents/_shipped/历史.md` (`name: history`, `genre: 历史`, description 强调"史实锚点 + 虚构戏剧冲突"; body 源自 `CONSULTANT_IDENTITY_HISTORY`).
- [ ] 2.3 Create `src/writer/agents/_shipped/言情.md` (`name: romance`, `genre: 言情`, description 强调"情感节拍 + GMC 推进"; body 源自 `CONSULTANT_IDENTITY_ROMANCE`).
- [ ] 2.4 Create `src/writer/agents/_shipped/玄幻.md` (`name: xuanhuan`, `genre: 玄幻`, description 强调"境界推进 + 副本叙事"; body 源自 `CONSULTANT_IDENTITY_XUANHUAN`).
- [ ] 2.5 Compute `sha256` for each of the 4 .md files; store in `BUILTIN_AGENT_SOURCES` tuples. Add a `_check_builtin_sources_drift()` helper that logs WARNING on sha mismatch (mirrors the skill loader's pattern).
- [ ] 2.6 Verify each .md frontmatter parses via `yaml.safe_load` and contains exactly `name` / `description` / `genre` (no extras that would break the `Agent` Protocol). Run a quick `python -c "import yaml; print(yaml.safe_load(open('src/writer/agents/_shipped/历史.md'.split('---')[1])))"` to spot-check.

## 3. Wire `AgentRegistry` into `EngineDeps` and `production_deps`

- [ ] 3.1 In `src/writer/engine/deps.py`, update `EngineDeps` Protocol to add:
  - `agent_registry: AgentRegistry`
  - `story_agent: StoryAgent` (renamed from `story_consultant`)
  - `rebind_agent_registry(self, new: AgentRegistry) -> EngineDeps`
- [ ] 3.2 In `_DefaultEngineDeps` dataclass, add `agent_registry: AgentRegistry` + `story_agent: StoryAgent` fields and the `rebind_agent_registry` method (uses `dataclasses.replace`, mirrors `rebind_directive_registry`).
- [ ] 3.3 In `production_deps(...)`, add `agent_registry: AgentRegistry | None = None` keyword (default to `built_agent_registry(project_root=root)`); pass `agent_registry=` and `story_agent=` to `_DefaultEngineDeps(...)`.
- [ ] 3.4 Update all call sites of `production_deps` to pass `agent_registry=` (or rely on default) + `story_agent=` (rename from `story_consultant=`). Most call sites won't need explicit kwargs (defaults work), but at least the test fixtures in `tests/test_engine_deps.py` will need a new field in any `PlainDeps` stub.

## 4. Rename `consultant` → `agent` (clean break)

- [ ] 4.1 Rename `src/writer/roles/story_consultant.py` → `src/writer/roles/story_agent.py`. Inside: rename class `StoryConsultant` → `StoryAgent`; rename `CONSULTANT_IDENTITY_*` references → `AGENT_IDENTITY_*`; update docstring "Story Consultant role" → "Story Agent role".
- [ ] 4.2 Rename `src/writer/roles/history_consultant.py` → `src/writer/roles/history_agent.py`. Class `HistoryConsultant` → `HistoryAgent`; `GENRE = "历史"` stays.
- [ ] 4.3 Rename `src/writer/roles/xuanhuan_consultant.py` → `xuanhuan_agent.py`. Class `XuanhuanConsultant` → `XuanhuanAgent`.
- [ ] 4.4 Rename `src/writer/roles/romance_consultant.py` → `romance_agent.py`. Class `RomanceConsultant` → `RomanceAgent`.
- [ ] 4.5 Update `src/writer/roles/__init__.py` to re-export from the new modules. Drop `StoryConsultant` / `HistoryConsultant` / etc. names — only the new `*Agent` names are exported.
- [ ] 4.6 Rename `src/writer/prompts/consultants.py` → `src/writer/prompts/agents.py`. Update imports inside (consultant module name → agent module name).
- [ ] 4.7 Rename `CONSULTANT_IDENTITY_*` constants in `src/writer/prompts/identity.py` → `AGENT_IDENTITY_*` (4 constants).
- [ ] 4.8 In `src/writer/prompts/registry.py`, update the import to `from writer.prompts.agents import ...` (renamed module).
- [ ] 4.9 In `src/writer/engine/deps.py`, rename field `story_consultant` → `story_agent`; rename `_GENRE_CONSULTANT` → `_GENRE_AGENT` (internal constant); rename `_consultant_for_genre` → `_agent_for_genre`; update the call site `_consultant_for_genre(resolved, genre)` to use the new helper.
- [ ] 4.10 In `src/writer/agent/__init__.py`, delete `NovelAgent = StoryConsultant` line (and `StoryConsultant` import if it was the only reason to import it). Keep `WriterCommandAgent = RuleBasedIntentRouter` (out of scope). Keep `IntentRouter` / `AgentAction` / `ActionType` / `Role` re-exports.
- [ ] 4.11 Run `rg "consultant|Consultant|CONSULTANT" src/ tests/ --type py` and fix every hit (rename / update import / update docstring). Expected: zero hits after this task.

## 5. Extend `AgentAction` with `kind` + `target_agent`

- [ ] 5.1 In `src/writer/routing/intent_router.py`, add to `AgentAction` (Pydantic, frozen):
  - `kind: Literal["command", "agent"] = "command"` (default preserves back-compat with existing call sites that don't pass `kind=`)
  - `target_agent: str | None = None`
- [ ] 5.2 In the router rule emitters / `RuleBasedIntentRouter` constructors, leave `kind="command"` (default). In the `LlmIntentRouter` output schema (per the design's Decision 4), add `target_agent` as a top-level field and emit `kind="agent"` when the LLM picks an agent.
- [ ] 5.3 Update any `AgentAction(...)` constructor calls in tests and cli to either pass the defaults explicitly (no change needed) or pass `kind="agent", target_agent="..."` for the new path.

## 6. Upgrade `LlmIntentRouter` to inject agent descriptions

- [ ] 6.1 In `src/writer/routing/llm_router.py` (wherever `LlmIntentRouter` is implemented), update the system prompt template to include a section listing the agent registry's `descriptions()` after the slash-command list. Truncate each description to ≤ 200 characters; cap total agents listed at 16.
- [ ] 6.2 Update the structured-output schema (the `_RouterDecision` Pydantic model or equivalent) to include `target_agent: str | None`. When the LLM fills in `target_agent`, construct `AgentAction(kind="agent", target_agent=target_agent, action_type=ActionType.ANSWER, command=None, args=...)`. When the LLM fills in `command`, keep existing behavior.
- [ ] 6.3 In the constructor of `LlmIntentRouter` (or `CompositeRouter`), accept an `agent_registry: AgentRegistry | None = None` keyword; if `None`, the router operates in legacy mode (no agent dispatch).
- [ ] 6.4 In `production_deps`, pass `agent_registry=agent_registry` into `_select_router(...)` (extend its signature to accept this kwarg).

## 7. Add `case "agent"` branch in engine loop

- [ ] 7.1 In `src/writer/engine/loop.py`, locate the `ActionEvent` dispatch match (the `match` on `action.kind` or equivalent) and add a new branch:
  ```python
  case "agent":
      agent = deps.agent_registry.require(action.target_agent or "")
      # Reuse the existing consultant call path; pass agent.body as the
      # system prompt override via _draft_outline_with_llm.
      ...
      yield Done(reason="answered", payload={"agent": action.target_agent, ...})
  ```
  (Detail shape TBD in apply phase; the principle is: reuse the StoryAgent LLM call path with the agent's body substituted as the system identity.)
- [ ] 7.2 If `deps.agent_registry.require(action.target_agent)` raises `AgentRegistryError`, catch it in the existing `except ToolError` block (or add a parallel `except AgentRegistryError`) and yield `ErrorEvent(message=...)` + `Done(reason="aborted", payload={"error": str(exc), "command": action.target_agent})`.

## 8. Mirror agents on `writer new` (`_seed_agents`)

- [ ] 8.1 In `src/writer/project/workspace.py`, add `_seed_agents(writer_root: Path, *, force: bool = False) -> list[Path]` mirroring `_seed_directives`:
  - Locates `src/writer/agents/_shipped/` via `importlib.resources.files("writer.agents._shipped")`
  - For each `*.md` in the shipped directory, copy to `<writer_root>/agents/<filename>`
  - Skip if `target.exists() and not force`
  - Per-file failures log WARNING and skip (do not block)
  - Returns list of created paths
- [ ] 8.2 In `_writer_meta_scaffolding`, append `created.extend(_seed_agents(writer_root, force=force))` after the `_seed_directives` call.
- [ ] 8.3 Update `_writer_meta_scaffolding`'s `targets` dict to replace the empty `agents/.gitkeep` with a no-op (the seed function will create real files; the `.gitkeep` becomes redundant but is harmless to keep for now). If `agents/other.md` etc. are created, delete the `.gitkeep` to avoid clutter.
- [ ] 8.4 Verify the `create_workspace` low-level API does **not** call `_seed_agents` (preserve back-compat; only `create_new_workspace` path triggers seeding, per design Decision 7).

## 9. Update `EngineSession.set_project_root` for agent_registry rebind

- [ ] 9.1 In `src/writer/session/engine_session.py`, locate `set_project_root`. After rebuilding `directive_registry` (current behavior), also rebuild `agent_registry` by calling `built_agent_registry(project_root=new_root)`.
- [ ] 9.2 Call `self.deps = self.deps.rebind_agent_registry(new_agent_registry)` (symmetric to existing `rebind_directive_registry` call). Update tests in `tests/test_engine_session.py` to assert this.

## 10. Write `tests/test_agent_registry.py`

- [ ] 10.1 Test: `parse_agent_file` extracts frontmatter + body from a valid `.md`.
- [ ] 10.2 Test: `parse_agent_file` raises `AgentRegistryError` on missing `name` / `description` / `genre`.
- [ ] 10.3 Test: `parse_agent_file` raises `AgentRegistryError` on empty body.
- [ ] 10.4 Test: `AgentRegistry` last-write-wins (project agent overrides built-in with same name).
- [ ] 10.5 Test: `AgentRegistry` raises on duplicate `name` within same scope.
- [ ] 10.6 Test: `AgentRegistry.descriptions()` returns `[{name, description, genre}]` sorted by name.
- [ ] 10.7 Test: `discover_project_agents(empty_dir) -> []`.
- [ ] 10.8 Test: `discover_project_agents(dir_with_one_md) -> [1 Agent]`.
- [ ] 10.9 Test: `built_agent_registry(project_root=...)` includes both built-in + project agents.
- [ ] 10.10 Test: built-in agent sha256 drift detection logs WARNING (mock log handler).

## 11. Update existing tests for the rename + AgentAction shape

- [ ] 11.1 In `tests/test_engine_deps.py`, update any `PlainDeps` stub to add `agent_registry: AgentRegistry = ...` and `story_agent: StoryAgent = ...` fields. Update any `production_deps(...)` calls passing `story_consultant=` → `story_agent=`.
- [ ] 11.2 In `tests/test_routing_intent.py` (or equivalent), update any `AgentAction(command="/x", args="...")` constructions to remain unchanged (default `kind="command"`). Add a new test for `AgentAction(kind="agent", target_agent="history", args="...")`.
- [ ] 11.3 In `tests/test_engine_loop.py`, add a `case "agent"` scenario: given an `AgentAction(kind="agent", target_agent="history", args="...")`, the loop should yield `ActionEvent` + `TextChunk` (LLM streaming) + `Done(reason="answered", payload={"agent": "history", ...})`.
- [ ] 11.4 In `tests/test_intent_router.py` (or wherever `LlmIntentRouter` is tested), add a test that injects a fake `BaseChatModel` returning `_RouterDecision(target_agent="history", ...)` and asserts the resulting `AgentAction.kind == "agent"` and `target_agent == "history"`.
- [ ] 11.5 Run `rg "consultant|Consultant" tests/ --type py` and confirm zero hits.

## 12. Update `tests/test_workspace.py` for `_seed_agents`

- [ ] 12.1 Add `test_create_workspace_with_agents_seeded`: `create_new_workspace(name, tmp_path, genres=["历史"])` should produce `<root>/.writer/agents/{other,历史,言情,玄幻}.md` (all 4 mirrored, not just 历史).
- [ ] 12.2 Add `test_create_workspace_does_not_seed_low_level`: `create_workspace(name, tmp_path, with_writer_meta=True)` (without `with_ideas_dir` or `create_new_workspace` path) does NOT create `.writer/agents/*.md`.
- [ ] 12.3 Add `test_agent_mirror_content_has_frontmatter`: read the mirrored `历史.md`, verify frontmatter contains `name: history` and body is non-empty.
- [ ] 12.4 Add `test_agent_mirror_respects_force`: with `force=True`, an existing `agents/历史.md` is overwritten with the shipped source.

## 13. Spec deltas + new capability

- [ ] 13.1 Create `openspec/changes/fea-agent-mirror/specs/shipped-agents/spec.md` (new capability). Requirements: (a) 4 built-in agents exist at `_shipped/<name>.md`; (b) frontmatter has `name` / `description` / `genre`; (c) `writer new` mirrors all 4 to `.writer/agents/`; (d) `AgentRegistry` last-write-wins; (e) project-level missing → built-in only. Mirror the structure of `openspec/specs/shipped-skills/spec.md`.
- [ ] 13.2 Create `openspec/changes/fea-agent-mirror/specs/intent-routing/spec.md` (delta) — MODIFIED requirements for: `AgentAction` has `kind` + `target_agent`; `LlmIntentRouter` sees agent descriptions; LLM output schema includes `target_agent`. Reference the existing `openspec/specs/intent-routing/spec.md` baseline and add the delta sections (`## ADDED Requirements` / `## MODIFIED Requirements` / `## REMOVED Requirements`).
- [ ] 13.3 Create `openspec/changes/fea-agent-mirror/specs/engine-loop/spec.md` (delta) — MODIFIED requirement for: `case "agent"` dispatch path, `Done(reason="answered", payload={"agent": ...})` payload contract. Reference the existing `openspec/specs/engine-loop/spec.md`.

## 14. OpenSpec validation

- [ ] 14.1 Run `openspec validate fea-agent-mirror --strict` and resolve all warnings/errors. Expected clean pass.
- [ ] 14.2 Run `openspec show fea-agent-mirror --json --type requirement` to confirm delta spec operations (ADDED for `shipped-agents`, MODIFIED for `intent-routing` and `engine-loop`) are recorded.

## 15. Final quality gate

- [ ] 15.1 Run `uv run ruff check src tests` — zero violations.
- [ ] 15.2 Run `uv run mypy src/writer` — zero errors.
- [ ] 15.3 Run `uv run pytest` — all tests pass (target: 320+ tests; baseline 322 per `MEMORY.md` 验证基线 + new `test_agent_registry.py` cases; minor net change as rename doesn't add tests but `_seed_agents` and agent dispatch add ~10-15).
- [ ] 15.4 Run e2e: `printf "/大纲 一个穿越到唐朝的程序员\n" | .venv/bin/writer` — should still hit the `answered` DoneReason (no behavioral regression for slash commands).
- [ ] 15.5 Run new e2e: `printf "我想写个穿越到唐朝的程序员和公主的爱情故事\n" | .venv/bin/writer` — verify `LlmIntentRouter` (when API key is set) picks `target_agent="history"` (because the input contains 唐朝/程序员) and the resulting `Done.payload["agent"] == "history"`.
- [ ] 15.6 Run `rg "consultant|Consultant|CONSULTANT" src/ tests/ docs/ --type py --type md` and confirm zero hits.
- [ ] 15.7 Update `docs/技术架构细节.md` / `docs/命令与用户流程.md` (if they reference consultant naming) — search for any docs that need updating; replace `consultant` / `Consultant` with `agent` / `Agent` consistently.

## 16. Update MEMORY.md

- [ ] 16.1 Append a new section to `/Users/zachary/.claude/projects/-Users-zachary-Desktop-codes-writer/memory/MEMORY.md` recording the change: clean rename consultant→agent, agent mirror via `.writer/agents/*.md`, AgentRegistry + IntentRouter integration, key gotchas (e.g. `AgentAction.kind` default preserves back-compat, `EngineContext` unchanged, agent body injected as system prompt via StoryAgent LLM call path).
