# Capability: engine-deps

## Purpose

Pure factory contract for `production_deps` (the single DI entry point
for the engine layer). `production_deps` MUST be a side-effect-free
factory: it must not read or write any file as part of assembling an
`EngineDeps` instance. The genre used to pick the `story_consultant`
subclass MUST be supplied by the caller, never inferred from disk.

## ADDED Requirements

### Requirement: production_deps is a pure factory with no filesystem IO

The system SHALL have `production_deps(settings=None, *, project_root=None, primary_router=None, genre="other") -> EngineDeps` in `src/writer/engine/deps.py` that never reads or writes any file as part of the call. All inputs come from the arguments; all output state is held in the returned `EngineDeps` instance.

#### Scenario: production_deps succeeds with no AGENT.md on disk
- **WHEN** a caller invokes `production_deps()` from a working directory that has no `AGENT.md` (e.g. a fresh temporary directory, or any process that has not bound a project)
- **THEN** the function MUST return a valid `EngineDeps` instance
- **AND** the function MUST NOT raise `FileNotFoundError` or any other IO exception caused by looking up project files
- **AND** `deps.story_consultant` MUST be a `StoryConsultant` (the default fallback for the default `genre="other"`)

#### Scenario: production_deps does not import writer.project at module load
- **WHEN** a test or REPL session inspects the imports of `src/writer/engine/deps.py`
- **THEN** the module MUST NOT contain a top-level `from writer.project ...` import
- **AND** any lazy `import writer.project.*` inside `production_deps` MUST have been removed

### Requirement: production_deps accepts an explicit genre argument

The system SHALL have `production_deps` accept `genre: str = "other"` as a keyword-only argument. The `genre` value is used to pick the `story_consultant` subclass via the same lookup table that powers `EngineSession.set_project_root` runtime genre switches.

#### Scenario: genre="历史" picks HistoryConsultant
- **WHEN** a caller invokes `production_deps(settings, project_root=root, genre="历史")` against a project root that contains a real `AGENT.md` whose `题材:` line says `都市悬疑`
- **THEN** `deps.story_consultant` MUST be a `HistoryConsultant`
- **AND** the factory MUST NOT read `AGENT.md` to make that decision (the caller's `genre` wins)

#### Scenario: genre="other" picks StoryConsultant fallback
- **WHEN** a caller invokes `production_deps(settings, project_root=root, genre="other")` (or omits `genre` entirely, since `"other"` is the default)
- **THEN** `deps.story_consultant` MUST be a `StoryConsultant`

#### Scenario: unknown genre falls through to StoryConsultant
- **WHEN** a caller invokes `production_deps(settings, project_root=root, genre="都市悬疑")` (or any string not in the whitelist `{历史, 言情, 玄幻}`)
- **THEN** `deps.story_consultant` MUST be a `StoryConsultant`

### Requirement: EngineSession is the only site that calls refresh_project_genre before production_deps

The system SHALL have `EngineSession.__post_init__` read the project's genre from `AGENT.md` via `self.refresh_project_genre()` and pass the result as `genre=...` to `production_deps`. This is the single source of truth for "what genre is the bound project" at session-construction time.

#### Scenario: EngineSession with project_root=None uses default genre
- **WHEN** `EngineSession()` is constructed with no arguments (so `project_root is None`)
- **THEN** `__post_init__` MUST skip `refresh_project_genre()` (no project to read)
- **AND** `production_deps` MUST be called with `genre="other"` (the field's default)

#### Scenario: EngineSession with project_root reads genre from AGENT.md
- **WHEN** `EngineSession(project_root=root)` is constructed and `root/AGENT.md` contains a `题材: 言情` line
- **THEN** `__post_init__` MUST call `self.refresh_project_genre()` and assign the result to `self.project_genre`
- **AND** `production_deps` MUST be called with `genre=self.project_genre` (i.e. `"言情"`)
- **AND** `deps.story_consultant` MUST be a `RomanceConsultant`

#### Scenario: EngineSession with injected deps skips genre refresh
- **WHEN** `EngineSession(project_root=root, deps=stub)` is constructed with an explicit `deps` value
- **THEN** `__post_init__` MUST NOT call `production_deps` at all
- **AND** `__post_init__` MUST NOT call `refresh_project_genre()` (the caller already wired the deps; the IO would be wasted)

### Requirement: CLI init_project passes resolved_genre through to production_deps

The system SHALL have `cli/main.py::init_project` pass the already-computed `resolved_genre` string to `_maybe_apply_init_brief`, which MUST forward it to `production_deps` as the `genre` argument. The CLI MUST NOT re-read `AGENT.md` to recover the genre at the `_maybe_apply_init_brief` call site — `init_project` is the single source of truth for the genre during the init flow.

#### Scenario: init_project --genre 言情 uses RomanceConsultant in init_brief
- **WHEN** a user runs `writer init 我的项目 --genre 言情`
- **THEN** `_maybe_apply_init_brief` MUST receive `genre="言情"`
- **AND** the `production_deps` it constructs MUST use `genre="言情"`
- **AND** `apply_init_brief` MUST run against a `RomanceConsultant`

#### Scenario: init_project default genre="other" uses StoryConsultant in init_brief
- **WHEN** a user runs `writer init 我的项目` with the interactive prompt choosing "其他" (which resolves to `"other"`)
- **THEN** `_maybe_apply_init_brief` MUST receive `genre="other"`
- **AND** `apply_init_brief` MUST run against a `StoryConsultant`
