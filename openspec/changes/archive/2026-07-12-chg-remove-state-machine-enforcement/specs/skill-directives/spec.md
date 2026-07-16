## MODIFIED Requirements

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