# Capability: skill-directives

## Purpose

Pure Markdown SKILL.md paradigm for project-level skills. Each directive is a ``<command>/SKILL.md`` directory (mirroring Claude Code's ``~/.claude/skills/`` layout) with optional ``references/`` and ``scripts/`` subdirectories. The engine reads the directive's body and ``@reference``-mentioned content into the LLM context, and the LLM uses the existing tool registry (``safe_read_file`` / ``safe_write_file`` / etc.) to do the actual work — no Python ``run()`` method, no Skill class.

This capability replaces the prior Python+Markdown mixed approach (``chg-project-skills``); the prior ``project-skills`` capability spec was archived without sync and is not in main. Discover / dispatch / engine-loop integration is governed entirely by this capability.
## Requirements
### Requirement: Skill file layout is `<command>/SKILL.md` directory

A directive MUST live in a directory named after its slash command. The directory MUST contain a ``SKILL.md`` file at its root. ``SKILL.md`` MUST be UTF-8 Markdown with a YAML frontmatter block followed by a Markdown body.

The directory MAY contain ``references/`` and ``scripts/`` subdirectories; both are optional.

#### Scenario: Directive directory contains SKILL.md
- **WHEN** `<project_root>/.writer/skills/<command>/SKILL.md` exists and parses as Markdown with YAML frontmatter
- **THEN** the loader MUST register a directive with ``command`` taken from the frontmatter
- **AND** the body (everything after the closing ``---`` of the frontmatter) MUST be available as the directive's instruction text

#### Scenario: Frontmatter command overrides directory name
- **WHEN** the directory is named ``大纲/`` but the frontmatter says ``command: /something_else``
- **THEN** the registered directive MUST use ``/something_else`` as its command, NOT ``/大纲``
- **AND** the discovery layer MUST NOT infer command from the directory name alone

#### Scenario: Missing or malformed frontmatter
- **WHEN** ``SKILL.md`` exists but has no frontmatter, or the frontmatter YAML fails to parse
- **THEN** the loader MUST log a WARNING and skip that directive
- **AND** MUST NOT raise

#### Scenario: Missing SKILL.md in skill directory
- **WHEN** the directory exists but has no ``SKILL.md`` (only ``references/`` or ``scripts/``)
- **THEN** the loader MUST skip that directory entirely
- **AND** MUST NOT raise

### Requirement: SkillDirective Protocol carries frontmatter + content

A ``SkillDirective`` MUST carry:

* ``command: str`` — slash command (from YAML frontmatter).
* ``description: str`` — human-readable description (from YAML frontmatter).
* ``body: str`` — full Markdown body of ``SKILL.md`` (frontmatter stripped, trailing whitespace normalized).
* ``references: dict[str, str]`` — ``{relpath: file_content}`` for every ``*.md`` under the ``<command>/references/`` subdirectory; absent subdirectory means empty dict.
* ``scripts: list[str]`` — relative paths of files under ``<command>/scripts/`` (e.g. ``["scripts/format_outline.py"]``); absent subdirectory means empty list.
* ``root: Path`` — absolute path of the directive's directory, so the engine can resolve script execution paths through ``safe_path``.

The ``requires_states`` field has been removed from the protocol (per ``chg-remove-state-machine-enforcement``). The engine no longer gates directives by lifecycle state — ``/大纲`` and ``/目录`` are reachable from every project state, including S4 where the writer needs to revise the outline mid-book. The LLM inside the directive body decides whether to append, overwrite, or view based on actual file existence, not on a precomputed state label.

#### Scenario: Directive with no references or scripts
- **WHEN** the directive's directory contains only ``SKILL.md``
- **THEN** ``directive.references`` MUST be ``{}``
- **AND** ``directive.scripts`` MUST be ``[]``

#### Scenario: References are keyed by relative path
- **WHEN** the directive's ``references/`` contains ``4-act-template.md`` and ``examples.md``
- **THEN** ``directive.references`` MUST be ``{"4-act-template.md": ..., "examples.md": ...}`` with content read UTF-8 and trailing newline stripped

#### Scenario: Scripts are listed but not loaded
- **WHEN** the directive's ``scripts/`` contains ``format_outline.py``
- **THEN** ``directive.scripts`` MUST be ``["scripts/format_outline.py"]``
- **AND** the script's content MUST NOT be loaded into the directive object (LLM reads it on demand via Bash tool)

#### Scenario: Non-md files under references are ignored
- **WHEN** ``references/`` contains ``image.png`` alongside ``template.md``
- **THEN** ``directive.references`` MUST contain only the ``.md`` entries
- **AND** MUST skip non-markdown files silently

### Requirement: Directive discovery scans the project skills directory

The system MUST provide ``discover_directives(project_root: Path) -> list[SkillDirective]`` which scans ``<project_root>/.writer/skills/*/SKILL.md`` and loads every well-formed directive.

The function MUST sort results by command (alphabetical on bytes) for deterministic ordering.

#### Scenario: No skills directory returns empty list
- **WHEN** ``<project_root>/.writer/skills/`` does not exist
- **THEN** ``discover_directives`` MUST return ``[]``

#### Scenario: Multiple directives are loaded
- **WHEN** ``.writer/skills/`` contains valid ``大纲/`` and ``目录/`` subdirectories
- **THEN** ``discover_directives`` MUST return one ``SkillDirective`` per subdirectory
- **AND** the returned list MUST be sorted by command

#### Scenario: Hidden directories are skipped
- **WHEN** ``.writer/skills/`` contains ``.hidden/`` or ``_draft/``
- **THEN** those entries MUST NOT be loaded
- **AND** MUST NOT cause an error

### Requirement: Per-directive failures are non-fatal

Per-directive failures (YAML parse error, missing ``command`` field, empty description) MUST be logged at WARNING with the file path and skipped. A broken directive MUST NOT prevent other directives from loading and MUST NOT prevent the REPL from starting.

The ``requires_states`` field is no longer required in frontmatter; its absence MUST NOT cause a directive to be rejected by the loader. A legacy ``requires_states`` line that survived from a pre-``chg-remove-state-machine-enforcement`` SKILL.md MUST be silently ignored (not parsed, not validated, not surfaced to the engine).

#### Scenario: One bad YAML does not block others
- **WHEN** ``<command1>/SKILL.md`` has invalid YAML and ``<command2>/SKILL.md`` is valid
- **THEN** ``discover_directives`` MUST return the ``<command2>`` directive
- **AND** MUST log a WARNING naming ``<command1>/SKILL.md``

#### Scenario: Frontmatter missing required field
- **WHEN** a directive's frontmatter has no ``command`` field
- **THEN** the loader MUST log a WARNING
- **AND** MUST NOT register the directive

### Requirement: DirectiveRegistry holds directives with Replace semantics

``DirectiveRegistry`` MUST hold ``SkillDirective`` instances keyed by their ``command``. When the same ``command`` appears more than once across layers (shipped, project, entry-point), the later layer MUST win (Replace semantics — same as the prior ``SkillRegistry`` rule per ``chg-project-skills`` Decision 8).

The ``state_matrix()`` method has been removed (per ``chg-remove-state-machine-enforcement``). The registry's introspection surface is now ``commands()`` + ``help_entries()`` only — there is no command-availability matrix because availability is no longer a registry concern. ``help_entries()`` MUST continue to derive from each directive's ``description``.

#### Scenario: Project directive replaces shipped by command
- **WHEN** ``.writer/skills/大纲/SKILL.md`` exists at the project level
- **THEN** ``registry.get("/大纲")`` MUST return the project's directive
- **AND** the shipped directive (if any) MUST NOT be reachable

#### Scenario: New project-only directive is added
- **WHEN** a project defines a file ``/我的新命令/SKILL.md`` with no shipped counterpart
- **THEN** ``registry.get("/我的新命令")`` MUST return that project directive
- **AND** no shipped directive is shadowed

#### Scenario: Registry exposes help_entries only
- **WHEN** a consumer calls ``registry.help_entries()``
- **THEN** the result MUST be derived from each directive's ``description``
- **AND** no source code outside ``directives/`` should need to know about SKILL.md parsing

#### Scenario: Registry has no state_matrix method
- **WHEN** a consumer inspects the ``DirectiveRegistry`` public API
- **THEN** it MUST expose ``commands()``, ``help_entries()``, ``get()``, and ``get_body_with_references()``
- **AND** MUST NOT expose a ``state_matrix()`` method

### Requirement: Directive execution emits standard event stream

Directive execution MUST emit the same event types as other engine paths (``TextChunk`` for streaming LLM output, ``Done(reason="answered")`` at completion). It MUST NOT emit ``Done(reason="command_pending")`` (which is reserved for unknown commands) or ``Done(reason="aborted")`` for normal completion.

The engine MUST NOT reject a directive dispatch based on project lifecycle state. ``/大纲`` in S4 (mid-book) MUST reach the directive body the same way it does in S1 (just-initialized); the LLM in the body decides whether to append, overwrite, or view based on actual file state.

#### Scenario: Directive succeeds
- **WHEN** the LLM completes the directive's task without raising
- **THEN** the engine MUST yield one or more ``TextChunk`` events with the LLM's streamed output
- **AND** finally yield ``Done(reason="answered", payload={"directive": "/<command>", ...})``

#### Scenario: Directive execution raises ToolError
- **WHEN** the LLM tool loop raises ``ToolError`` during directive execution
- **THEN** the engine MUST yield ``ErrorEvent`` followed by ``Done(reason="aborted")``
- **AND** the behavior MUST match the existing ``call_tool`` error path

#### Scenario: Directive dispatched in mid-book S4 state
- **WHEN** the project has progressed to S4 (``manuscript/`` has chapters) and the user invokes ``/大纲 补充第 5 章前后伏笔``
- **THEN** the engine MUST NOT block the dispatch on lifecycle state
- **AND** the directive body MUST execute, with the LLM reading the existing ``outline/大纲.md`` and deciding to append rather than overwrite

### Requirement: built_directive_registry composes layers

``built_directive_registry(project_root: Path | None = None)`` MUST compose three layers in order (later wins on collision):

1. ``discover_shipped_directives()`` — reads ``src/writer/skills/_shipped/*/SKILL.md`` via ``importlib.resources``
2. ``discover_directives(project_root)`` — only when ``project_root`` is provided
3. ``discover_entry_point_directives()`` — Python entry-point plugins (extension point for future)

#### Scenario: project_root=None returns shipped only
- **WHEN** ``built_directive_registry(project_root=None)`` is called
- **THEN** the resulting registry MUST contain the 4 shipped directives (大纲, 目录, 续写, 改)
- **AND** MUST NOT include any project-level directives

#### Scenario: project_root given adds the project layer
- **WHEN** ``built_directive_registry(project_root=tmp_path)`` is called and ``tmp_path/.writer/skills/大纲/SKILL.md`` exists
- **THEN** the resulting registry MUST contain a directive for ``/大纲``
- **AND** the project's directive MUST shadow the shipped one

### Requirement: create_new_workspace seeds shipped directives

``create_new_workspace`` (the public entry used by ``writer new``) MUST copy every shipped directive's full directory (``SKILL.md`` + ``references/`` + ``scripts/`` if present) into ``<project_root>/.writer/skills/<command>/``.

After copying, the project's directory contains the same files as ``_shipped``; the user can edit freely and the discovery layer treats them identically to user-added directives.

#### Scenario: writer new ships all four built-in directives
- **WHEN** ``create_new_workspace(name, base_dir)`` succeeds
- **THEN** ``<root>/.writer/skills/大纲/SKILL.md`` MUST exist
- **AND** ``<root>/.writer/skills/目录/SKILL.md`` MUST exist
- **AND** ``<root>/.writer/skills/续写/SKILL.md`` MUST exist
- **AND** ``<root>/.writer/skills/改/SKILL.md`` MUST exist
- **AND** each directive's ``references/`` MUST be copied verbatim

#### Scenario: Existing files are not overwritten on re-seed
- **WHEN** ``<root>/.writer/skills/大纲/SKILL.md`` already exists at the time of seeding
- **THEN** the seed operation MUST leave the existing file untouched
- **AND** MUST NOT raise

#### Scenario: create_workspace (low-level) does NOT seed directives
- **WHEN** ``create_workspace(name, base_dir)`` (without ``with_writer_meta``) is called
- **THEN** the function MUST NOT create any files under ``.writer/skills/``
- **AND** the function MUST continue to behave exactly as before this change

### Requirement: Runner dispatches directives via LLM instruction injection

When the engine loop receives a ``run_command`` action whose ``command`` matches a registered directive, the engine MUST inject the directive's body and referenced content into the LLM context, then let the existing LLM tool loop execute the work.

#### Scenario: Directive dispatch is invoked
- **WHEN** ``deps.directive_registry.get("/大纲")`` returns a directive
- **AND** the action's ``command`` is ``"/大纲"``
- **THEN** the engine MUST yield events from a directive execution path
- **AND** the directive's ``body`` MUST be included in the system message sent to the LLM

#### Scenario: @reference syntax is resolved
- **WHEN** the directive body contains ``@reference references/4-act-template.md``
- **THEN** the engine MUST read ``<directive.root>/references/4-act-template.md``
- **AND** include its content in the system message alongside the directive body

#### Scenario: Unreferenced reference files are not sent
- **WHEN** ``references/`` contains ``template.md`` and ``examples.md``
- **AND** only ``template.md`` is referenced via ``@reference`` in the body
- **THEN** the engine MUST include ``template.md``'s content
- **AND** MUST NOT include ``examples.md``'s content in this turn

#### Scenario: Missing @reference target is logged
- **WHEN** the directive body references a non-existent file
- **THEN** the engine MUST log a WARNING naming the missing path
- **AND** MUST continue dispatch (the LLM sees the warning text rather than the missing content)

### Requirement: Engine rebuilds directive registry on project_root change

When ``EngineSession.set_project_root(new_root)`` changes the bound project, the session MUST rebuild ``deps.directive_registry`` from the new project root so that project-level directives in the new project take effect on subsequent REPL turns.

The rebuild MUST go through a new ``EngineDeps.rebind_directive_registry(new)`` method symmetric to the prior ``rebind_tool_runtime`` / ``rebind_story_consultant``. ``rebind_skill_registry`` is kept as a back-compat alias.

#### Scenario: set_project_root rebuilds the directive registry
- **WHEN** ``session.set_project_root(new_root)`` is called with a different path than the current ``project_root``
- **THEN** ``session.deps.directive_registry.get("/大纲")`` (after the call) MUST reflect the directives visible in the new project
- **AND** the registry MUST be a different object than before the call

#### Scenario: Same project_root is a no-op
- **WHEN** ``session.set_project_root(current_root)`` is called with the same path
- **THEN** the call MUST return without rebuilding the registry
- **AND** ``session.deps.directive_registry`` MUST be the same object as before the call

#### Scenario: EngineDeps exposes rebind_directive_registry
- **WHEN** a consumer inspects the ``EngineDeps`` Protocol
- **THEN** the Protocol MUST declare a ``rebind_directive_registry(new: DirectiveRegistry) -> EngineDeps`` method
- **AND** the production ``_DefaultEngineDeps`` MUST implement it using ``dataclasses.replace(self, directive_registry=new)``

