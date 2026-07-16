## 1. Extend Skill Protocol

- [x] 1.1 In `src/writer/skills/protocol.py`, add `extra_instructions: str` field to the `Skill` Protocol with default empty string. Update the docstring to document the new field and explain when consumers (future LLM-backed skills) should populate vs. leave it empty.
- [x] 1.2 In `src/writer/skills/__init__.py`, re-export `discover_project_skills` (added in step 2) and any new public types from `loader` / `builtin_sources`.

## 2. Project skill loader

- [ ] 2.1 Create `src/writer/skills/loader.py` with `discover_project_skills(project_root: Path) -> list[Skill]`. Scan `<project_root>/.writer/skills/*.py`; for each file use `importlib.util.spec_from_file_location("user_skill_<basename>", path)` + `module_from_spec` + `loader.exec_module(module)`. Look for a top-level `Skill` instance OR a single `Skill` subclass (no-arg construct). Wrap every failure in `log.warning` and `continue`.
- [ ] 2.2 In the same module, after loading the Python file, attempt to read `<basename>.md` (UTF-8) from the same directory. If present, set the skill's `extra_instructions` to the file's content (strip only the trailing newline). If absent, leave `extra_instructions` at its default empty string.
- [x] 2.3 Add unit tests in `tests/test_skill_loader.py` covering: empty dir returns `[]`; single valid `.py` returns the skill; `_foo.py` / `.bar.py` are skipped; `__pycache__/` is skipped; pre-built `Skill` instance is accepted; `Skill` subclass is no-arg constructed; companion `.md` populates `extra_instructions`; missing `.md` defaults to `""`; syntax error in one file does not block the other; module without a `Skill` is skipped; class with empty `command` is skipped.

## 3. Built-in skill source registry

- [x] 3.1 Create `src/writer/skills/builtin_sources.py` exporting a list of records (one per built-in skill): `(command: str, mirror_filename: str, source_module: str, class_name: str, doc_filename: str, mirror_header: str)`. Hardcode the entries for `OutlineSkill` / `TocSkill` / `ContinueWritingSkill` / `ReviseSkill` (commands `/大纲` / `/目录` / `/续写` / `/改`).
- [ ] 3.2 Add unit tests in `tests/test_skill_loader.py` (or a new `tests/test_builtin_sources.py`) asserting the registry has exactly 4 entries and each entry's `command` / `mirror_filename` matches.

## 4. SkillRegistry: later-wins semantics

- [x] 4.1 In `src/writer/skills/registry.py`, change `SkillRegistry.__init__` to use a dict-based upsert (later `command` replaces earlier) instead of raising on duplicates. Update the docstring to reflect the Replace semantics. Keep `_validate_skill` (it still catches malformed entries).
- [ ] 4.2 Update `tests/test_skill_registry.py::test_duplicate_commands_raise` → `test_later_wins_over_earlier`. Verify the new behavior matches the spec (project skill overrides built-in by command).

## 5. built_skill_registry with project_root

- [x] 5.1 Add a `project_root: Path | None = None` keyword argument to `built_skill_registry()`. When provided, call `discover_project_skills(project_root)` and include the result between the built-in layer and the entry-point plugin layer (Replace semantics already in place from step 4).
- [ ] 5.2 Update `tests/test_skill_registry.py` with two new cases: `project_root=None` matches legacy behavior (no project skills added); `project_root=tmp_path` with a valid `大纲.py` in `tmp_path/.writer/skills/` includes the project skill in the registry.

## 6. Workspace seeding (mirror built-in skills)

- [x] 6.1 In `src/writer/project/workspace.py`, extend `_writer_meta_scaffolding` to call a new helper `_seed_skill_mirrors(writer_root: Path, *, force: bool) -> list[Path]`. The helper iterates over the registry from step 3 and, for each entry, writes `<writer_root>/skills/<mirror_filename>.py` (using the source module's class definition + the hardcoded `mirror_header`) and `<writer_root>/skills/<mirror_filename>.md` (using the `doc_filename` content; can be a small hardcoded body for now). Skip files that already exist unless `force=True`.
- [x] 6.2 Wire `_seed_skill_mirrors` into `_writer_meta_scaffolding` so it runs only when `with_writer_meta=True` (the `create_new_workspace` path), NOT when `create_workspace` is called without that flag.
- [ ] 6.3 Extend `tests/test_workspace.py` with cases: `create_new_workspace` writes 4 `.py` + 4 `.md` files under `.writer/skills/`; each `.py` contains the matching `class` block; `create_workspace` (without `with_writer_meta`) does NOT create any skill files; existing `.py` files are NOT overwritten on re-seed; `--force` overwrites.

## 7. EngineDeps.rebind_skill_registry

- [x] 7.1 In `src/writer/engine/deps.py`, add `rebind_skill_registry(self, new_registry: SkillRegistry) -> EngineDeps` to the `EngineDeps` Protocol (with a brief `...` body, matching the existing `rebind_tool_runtime` / `rebind_story_consultant` style).
- [x] 7.2 In `_DefaultEngineDeps`, implement the new method using `dataclasses.replace(self, skill_registry=new_registry)`.
- [ ] 7.3 Add a unit test in `tests/test_engine_deps.py` asserting the production wiring exposes a working `rebind_skill_registry` (smoke check: call it, get a new deps, the new registry is reflected).

## 8. EngineSession.set_project_root rebuilds skill_registry

- [x] 8.1 In `src/writer/session/engine_session.py`, extend `set_project_root` to call `built_skill_registry(project_root=new_root)` after the `rebind_tool_runtime` / `rebind_story_consultant` chain, and `self.deps = self.deps.rebind_skill_registry(new_registry)`. Keep the existing `if new_root == self.project_root: return` no-op guard so unchanged-path calls skip the rebuild.
- [x] 8.2 In `__post_init__`, when `self.deps is None and self.project_root is not None`, pass `project_root=self.project_root` to `production_deps` (or have `production_deps` accept it transitively) so the initial registry already reflects the bound project. If `production_deps` does not accept `project_root`, refactor minimally: add the parameter and forward it to `built_skill_registry` inside the factory.
- [ ] 8.3 Extend `tests/test_engine_session.py` with cases: `set_project_root` rebuilds the registry; same-path call is a no-op (registry object identity preserved); production-deps receives `project_root` so the initial registry already contains project skills.

## 9. Engine dispatch sanity check

- [ ] 9.1 Verify (no code change expected) that `src/writer/engine/loop.py` line ~152 still works: when a `run_command` action targets a slash command that maps to a project-level skill, the engine MUST yield the skill's events followed by `Done(reason="command_pending", ...)`. Add a focused test in `tests/test_skill_dispatch.py` that creates a project with a custom skill (e.g. `/hello` that yields one `TextChunk` and a `Done`), binds the engine session, runs the engine with `AgentAction(action_type="run_command", command="/hello")`, and asserts the expected events.
- [ ] 9.2 Confirm no change to `src/writer/routing/intent_router.py` is required (the router only emits `action_type` + `command`; the registry does the rest). If a test fixture for the rule-based router needs updating, do so.

## 10. OpenSpec validation + final quality gate

- [ ] 10.1 Run `openspec validate chg-project-skills --strict` and resolve all warnings/errors. Expected clean pass.
- [ ] 10.2 Run `uv run ruff check src tests` — zero violations.
- [ ] 10.3 Run `uv run mypy src/writer` — zero errors. Watch for the new `extra_instructions` field breaking fake `Skill` implementations in tests (apply: add `extra_instructions: str = ""` to any test stub that subclasses `Skill` or sets the three required attributes manually).
- [ ] 10.4 Run `uv run pytest` — all tests pass. Target: 332+ tests (baseline 322 from chg-remove-rag archive; +10 from `tests/test_skill_loader.py` per task 2.3).
- [ ] 10.5 Run e2e: `writer new /tmp/rag-e2e-test` and verify `<root>/.writer/skills/` contains the 4 mirrored `.py` + 4 `.md` files. Then `printf "/大纲 一个穿越到唐朝的程序员\n" | writer --project-root /tmp/rag-e2e-test` and confirm the engine still works (the project-level mirror matches the built-in behavior, so output should be identical to before).
