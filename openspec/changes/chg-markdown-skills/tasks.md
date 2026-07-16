## 1. Working tree cleanup (delete obsolete Python skill code)

- [x] 1.1 Delete `src/writer/skills/outline.py`, `toc.py`, `continue_writing.py`, `revise.py` (4 Python class implementations, replaced by shipped SKILL.md).
- [x] 1.2 Delete `src/writer/skills/loader.py` (Python importlib loader — replaced by Markdown `directive_discovery`).
- [x] 1.3 Delete `src/writer/skills/builtin_sources.py` (mirror metadata tuple — replaced by shipped `_shipped/` directory).
- [x] 1.4 In `src/writer/skills/__init__.py`, remove re-exports of deleted symbols; keep only the new symbols (`SkillDirective`, `DirectiveRegistry`, `discover_directives`, etc.).
- [x] 1.5 Verify `rg "from writer.skills.outline|OutlineSkill|TocSkill|ContinueWritingSkill|ReviseSkill"` returns only false positives (e.g., comment references in docs).

## 2. SkillDirective Protocol + DirectiveRegistry

- [x] 2.1 In `src/writer/skills/protocol.py`, replace the `Skill` Protocol with a frozen `SkillDirective` dataclass carrying: `command: str`, `description: str`, `requires_states: frozenset[ProjectState]`, `body: str`, `references: dict[str, str]`, `scripts: list[str]`, `root: Path`. Update the module docstring to reflect the Markdown paradigm.
- [x] 2.2 In `src/writer/skills/registry.py`, rename `SkillRegistry` → `DirectiveRegistry`. Internal dict value type changes from `Skill` to `SkillDirective`. Keep `get()` / `commands()` / `help_entries()` / `state_matrix()` interfaces identical. Keep the last-write-wins semantics from `chg-project-skills`.
- [x] 2.3 In `src/writer/skills/__init__.py`, re-export `SkillDirective`, `DirectiveRegistry`, and the discovery helpers (added in step 3).
- [x] 2.4 Update `tests/test_skill_registry.py` → rename to `tests/test_directive_registry.py`. Replace `Skill`-based fixtures with `SkillDirective`-based ones. Cover: last-write-wins across layers; help_entries and state_matrix derive from directive metadata.

## 3. Markdown directive discovery

- [x] 3.1 Create `src/writer/skills/directive_discovery.py` with two public functions:
  - `discover_directives(project_root: Path) -> list[SkillDirective]` — scans `<project_root>/.writer/skills/*/SKILL.md`.
  - `discover_shipped_directives() -> list[SkillDirective]` — uses `importlib.resources.files("writer.skills._shipped")` to list the 4 shipped directories.
- [x] 3.2 Add `_parse_skill_md(path: Path) -> SkillDirective | None` helper: split frontmatter (regex ``^---\n(.*?)\n---\n`` + ``yaml.safe_load``) and body; read ``references/*.md`` into the dict; list ``scripts/*.py`` paths; return ``None`` on failure with `log.warning`.
- [x] 3.3 Add `tests/test_directive_discovery.py` covering: missing skills dir returns `[]`; valid SKILL.md with frontmatter parses; invalid YAML is skipped without raising; non-md reference files are skipped; missing frontmatter fields are skipped; hidden directories are skipped; results are sorted by command.

## 4. Shipped SKILL.md packages

- [x] 4.1 Create `src/writer/skills/_shipped/大纲/SKILL.md` with valid frontmatter (`command: /大纲`, `description: 生成或查看大纲`, `requires_states: [INITIALIZED, HAS_OUTLINE]`) and a body that follows the spec template (role, inputs, tool calls, output paths, edge cases). Body MUST reference at least one ``references/`` file via `@reference`.
- [x] 4.2 Create `src/writer/skills/_shipped/大纲/references/4-act-template.md` (四幕模板) and `examples.md` (示例输出). Each ≥500 bytes.
- [x] 4.3 Create `src/writer/skills/_shipped/目录/SKILL.md` (read outline/大纲.md, call StoryConsultant.draft_toc, write outline/toc.md, refresh AGENT.md) plus `references/chapter-format.md`.
- [x] 4.4 Create `src/writer/skills/_shipped/续写/SKILL.md` (read latest chapter, call StoryConsultant.continue_chapter, append to draft) plus `references/style-guide.md`.
- [x] 4.5 Create `src/writer/skills/_shipped/改/SKILL.md` (read chapter, take edit instruction, call StoryConsultant.revise_chapter) plus `references/diff-format.md`.
- [x] 4.6 Update `pyproject.toml`'s `[tool.hatch.build.targets.wheel.force-include]` (or equivalent) to ensure the `_shipped/` directory is packaged with the wheel. Verify with `uv build` and `python -c "import importlib.resources; print(list((importlib.resources.files('writer.skills._shipped')).iterdir()))"`.
- [x] 4.7 Add `tests/test_shipped_directives.py` covering: 4 directives load successfully; each SKILL.md frontmatter is valid; each has ≥1 reference file ≥500 bytes; requires_states values are valid ProjectState members.

## 5. built_directive_registry composes layers

- [x] 5.1 Add `built_directive_registry(project_root: Path | None = None) -> DirectiveRegistry` (replaces `built_skill_registry` from `chg-project-skills`). Layer order: shipped → project → entry-point (last-wins).
- [x] 5.2 Update `tests/test_directive_registry.py` with two new cases: `project_root=None` returns the 4 shipped directives; `project_root=tmp_path` with a valid `大纲/SKILL.md` includes the project directive and shadows shipped.

## 6. Workspace seeding

- [x] 6.1 In `src/writer/project/workspace.py`, replace `_seed_skill_mirrors` with `_seed_directives(writer_root: Path, *, force: bool = False) -> list[Path]`. Use `importlib.resources.files("writer.skills._shipped")` to enumerate the 4 shipped directories; copy each file (SKILL.md + references/ + scripts/) verbatim into `<writer_root>/skills/<command>/`. Skip files that already exist unless `force=True`.
- [x] 6.2 Wire `_seed_directives` into `_writer_meta_scaffolding` so it runs only when `with_writer_meta=True` (the `create_new_workspace` path). Low-level `create_workspace` does NOT seed directives.
- [x] 6.3 Extend `tests/test_workspace.py` with cases: `create_new_workspace` creates `大纲/SKILL.md`, `目录/SKILL.md`, `续写/SKILL.md`, `改/SKILL.md` (directories, not files); each subdirectory contains a SKILL.md; `references/` files are copied verbatim; existing SKILL.md files are NOT overwritten on re-seed.

## 7. Engine directive dispatch

- [x] 7.1 In `src/writer/engine/loop.py`, modify the `case "run_command"` branch: when `action.command` matches `deps.directive_registry`, dispatch via the new `_run_directive(directive, ctx, deps, cfg)` helper instead of the legacy `_run_skill(...)` path. The legacy Python Skill path may be kept as a fallback for test stubs but should not be the default.
- [x] 7.2 Add `_run_directive(...)` async generator: resolve `@reference path` mentions in `directive.body`, read those files from `directive.root / path`, prepend the body + a "参考资料" section to the system message, then delegate to `deps.tool_loop.run(...)` for LLM-driven tool execution. Stream events unchanged.
- [x] 7.3 Add `tests/test_directive_dispatch.py` covering: directive dispatch yields the expected TextChunk + Done sequence when an LLM mock is supplied; `@reference` syntax resolves content; missing references log a WARNING but don't crash; `Done(reason="answered", payload={"directive": ...})` is emitted on success; `Done(reason="aborted")` is emitted on `ToolError`.

## 8. EngineDeps + EngineSession rewiring

- [x] 8.1 In `src/writer/engine/deps.py`, rename `skill_registry` field to `directive_registry` and `rebind_skill_registry` to `rebind_directive_registry`. Update the Protocol declarations and the `_DefaultEngineDeps` dataclass + methods.
- [x] 8.2 In `production_deps(...)`, replace `built_skill_registry(project_root=root)` with `built_directive_registry(project_root=root)`.
- [x] 8.3 In `src/writer/session/engine_session.py`, update `set_project_root(...)` to call `built_directive_registry(...)` + `rebind_directive_registry(...)` instead of the skill variants.
- [x] 8.4 In `src/writer/cli/main.py`, update any references to `skill_registry` (in `build_repl_commands` / `print_repl_help` / etc.) to use `directive_registry`. The interface (commands / help_entries / state_matrix) is unchanged, so most call sites need only a rename.
- [x] 8.5 Update `tests/test_engine_deps.py` and `tests/test_engine_session.py` (including the `PlainDeps` stub) to use the new field names.

## 9. Test rewrites

- [x] 9.1 Delete `tests/test_skill_loader.py` (no longer relevant).
- [x] 9.2 Delete `tests/test_skill_registry.py` content referencing the old `Skill` class; the renamed `tests/test_directive_registry.py` already covers the registry behavior.
- [x] 9.3 Update `tests/test_engine.py` and `tests/test_engine_session.py` references from `foreshadow_query` to `foreshadow_search` (already done in `chg-remove-rag`) and from `skill_registry` to `directive_registry`.
- [x] 9.4 Update `tests/test_skill_dispatch.py` to use the directive dispatch path instead of `Skill.run(...)`.
- [x] 9.5 Update `tests/test_tools.py` and any other test that imports from `writer.skills` to use the new public API.

## 10. OpenSpec validation + final quality gate

- [x] 10.1 Run `openspec validate chg-markdown-skills --strict` and resolve all warnings/errors. Expected clean pass.
- [x] 10.2 Run `uv run ruff check src tests` — zero violations.
- [x] 10.3 Run `uv run mypy src/writer` — zero errors. Watch for the `Path` field in `SkillDirective` breaking fake directives in tests; supply a real `tmp_path` in fixtures.
- [x] 10.4 Run `uv run pytest` — all tests pass. Target: 360+ tests (350 baseline from `chg-project-skills` apply + 10 new from `tests/test_directive_discovery.py` + `tests/test_directive_dispatch.py` + `tests/test_shipped_directives.py`).
- [x] 10.5 Run e2e: `writer new /tmp/e2e-test` and verify `<root>/.writer/skills/大纲/SKILL.md` + `references/*.md` exist. Then `printf "/大纲 一个穿越到唐朝的程序员\n" | writer --project-root /tmp/e2e-test` and verify the engine dispatches the directive and the LLM (mocked or real) produces a sensible response.