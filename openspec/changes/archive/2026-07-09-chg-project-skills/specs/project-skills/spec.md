## ADDED Requirements

### Requirement: Skill Protocol has extra_instructions field

The ``Skill`` Protocol MUST define an ``extra_instructions: str`` field with a default empty string. Built-in skills and project-level skills that do not need supplementary LLM instructions MUST leave the field at its default; project-level skills that ship a same-named ``<command>.md`` MUST populate it from the file contents.

The existing three Protocol fields (``command`` / ``description`` / ``requires_states``) MUST remain unchanged in semantics and ordering. Adding ``extra_instructions`` is strictly additive — every existing implementation continues to type-check without modification.

#### Scenario: Skill Protocol exposes extra_instructions
- **WHEN** a consumer inspects ``writer.skills.protocol.Skill``
- **THEN** the Protocol MUST declare a ``extra_instructions`` annotation
- **AND** the field MUST default to the empty string when not provided by an implementation

#### Scenario: Built-in skill leaves extra_instructions empty
- **WHEN** ``OutlineSkill()`` is instantiated
- **THEN** ``skill.extra_instructions`` MUST equal ``""``
- **AND** the skill's behavior MUST be unchanged from before this change

### Requirement: Project skills directory layout

The system MUST treat ``<project_root>/.writer/skills/`` as a project-local skill overlay. Each skill in that directory MUST consist of at least one Python file whose basename (without ``.py``) equals the slash command the skill implements. Optional companion Markdown files with the same basename and ``.md`` extension provide supplementary instructions.

#### Scenario: Skill file is named after its command
- **WHEN** ``<project_root>/.writer/skills/大纲.py`` exists
- **THEN** the loader MUST register a skill with ``command == "/大纲"`` from that file
- **AND** any other slash command string in the file MUST be ignored

#### Scenario: Companion Markdown is read into extra_instructions
- **WHEN** ``<project_root>/.writer/skills/大纲.md`` exists alongside ``大纲.py``
- **THEN** the loader MUST set the resulting skill's ``extra_instructions`` to the Markdown file's UTF-8 content
- **AND** the loader MUST strip only the trailing newline; the rest of the content MUST be preserved verbatim

#### Scenario: Missing Markdown is allowed
- **WHEN** ``<project_root>/.writer/skills/大纲.py`` exists but ``大纲.md`` does not
- **THEN** the skill MUST still be registered
- **AND** its ``extra_instructions`` MUST default to ``""``

### Requirement: Project skills are loaded via importlib

The system MUST provide ``discover_project_skills(project_root: Path) -> list[Skill]`` which scans ``<project_root>/.writer/skills/*.py`` and dynamically loads each file using ``importlib.util.spec_from_file_location``. The function MUST return one ``Skill`` instance per loadable file.

#### Scenario: Empty skills directory returns empty list
- **WHEN** ``<project_root>/.writer/skills/`` does not exist, or contains no ``.py`` files
- **THEN** ``discover_project_skills(project_root)`` MUST return ``[]``

#### Scenario: Hidden and dunder files are skipped
- **WHEN** the directory contains ``_foo.py`` / ``.bar.py`` / ``__pycache__/``
- **THEN** those entries MUST NOT be loaded
- **AND** they MUST NOT cause an error

#### Scenario: Skill class is instantiated with no arguments
- **WHEN** a loaded module defines a single ``Skill`` subclass (no required ``__init__`` args)
- **THEN** the loader MUST instantiate the class with no arguments
- **AND** the resulting instance MUST pass ``_validate_skill``

#### Scenario: Pre-built Skill instance is accepted
- **WHEN** a loaded module exposes a top-level variable whose value is already a ``Skill`` instance
- **THEN** the loader MUST use that instance as-is
- **AND** the instance MUST pass ``_validate_skill``

### Requirement: Failure to load a project skill is non-fatal

Per-skill load failures (syntax errors, import errors, missing ``Skill`` class, validation errors) MUST be logged at WARNING with the file path and skipped. A single broken project skill MUST NOT prevent other project skills from loading and MUST NOT prevent the REPL from starting.

#### Scenario: Syntax error in one file does not block others
- **WHEN** ``<project_root>/.writer/skills/大纲.py`` has a ``SyntaxError`` and ``目录.py`` is valid
- **THEN** ``discover_project_skills`` MUST return the ``目录`` skill
- **AND** MUST log a WARNING containing the ``大纲.py`` path and the syntax error
- **AND** MUST NOT raise

#### Scenario: Module that does not expose a Skill is skipped
- **WHEN** a loaded module defines neither a ``Skill`` subclass nor a ``Skill`` instance
- **THEN** the loader MUST log a WARNING naming the file
- **AND** MUST NOT include the file in the returned list
- **AND** MUST NOT raise

#### Scenario: Skill with invalid metadata is skipped
- **WHEN** a loaded module defines a class whose ``command`` is empty / does not start with ``"/"``
- **THEN** the loader MUST log a WARNING
- **AND** MUST NOT include it in the returned list

### Requirement: Project skills override built-in skills by command

When ``discover_project_skills(project_root)`` and ``BUILTIN_SKILLS`` (or entry-point plugins) define the same ``command``, the project-level instance MUST win. ``SkillRegistry`` MUST be assembled as ``BUILTIN_SKILLS + project + entry_point`` with later registrations replacing earlier ones for the same command.

#### Scenario: Project skill replaces built-in by command
- **WHEN** a project defines ``/大纲`` and the built-in ``OutlineSkill`` also defines ``/大纲``
- **THEN** the resulting registry's ``get("/大纲")`` MUST return the project-level instance
- **AND** the built-in ``OutlineSkill`` MUST NOT be reachable via the registry

#### Scenario: New project-only command is added
- **WHEN** a project defines a file ``/我的新命令.py`` with no corresponding built-in
- **THEN** the resulting registry's ``get("/我的新命令")`` MUST return that project skill
- **AND** no built-in is shadowed

#### Scenario: Entry-point plugin overrides both
- **WHEN** an entry-point plugin, a project skill, and a built-in all define the same command
- **THEN** the entry-point instance wins (last registration)
- **AND** both the project and the built-in MUST NOT be reachable

### Requirement: New project workspaces are seeded with skill mirrors

``create_new_workspace`` (the public entry point used by ``writer new``) MUST seed ``<project_root>/.writer/skills/`` with one ``.py`` and one ``.md`` file per built-in skill, so the user has a visible, editable copy of every project-relevant skill.

#### Scenario: create_new_workspace writes all built-in skill mirrors
- **WHEN** ``create_new_workspace(name, base_dir)`` succeeds
- **THEN** ``<root>/.writer/skills/大纲.py`` / ``目录.py`` / ``续写.py`` / ``改.py`` MUST exist
- **AND** ``<root>/.writer/skills/大纲.md`` / ``目录.md`` / ``续写.md`` / ``改.md`` MUST exist
- **AND** each ``.py`` MUST contain the corresponding built-in skill's class definition plus a header comment

#### Scenario: Mirror .py contains the built-in class
- **WHEN** the user reads ``<root>/.writer/skills/大纲.py``
- **THEN** the file MUST define a class with the same ``command`` / ``description`` / ``requires_states`` as the built-in ``OutlineSkill``
- **AND** the file MUST contain a header comment explaining "this is a project-level override" and pointing at the original ``writer.skills.outline`` source

#### Scenario: Mirror .md describes the skill
- **WHEN** the user reads ``<root>/.writer/skills/大纲.md``
- **THEN** the file MUST contain at least the skill's description and a one-paragraph note about how the user can adjust it

#### Scenario: create_workspace (low-level) does NOT mirror skills
- **WHEN** ``create_workspace(name, base_dir)`` (without ``with_writer_meta``) is called
- **THEN** the function MUST NOT create any files under ``.writer/skills/``
- **AND** the function MUST continue to behave exactly as before this change

#### Scenario: Existing files are not overwritten
- **WHEN** ``<root>/.writer/skills/大纲.py`` already exists at the time of seeding
- **THEN** the seed operation MUST leave the existing file untouched
- **AND** MUST NOT raise

### Requirement: EngineSession rebuilds skill registry on project_root change

When ``EngineSession.set_project_root(new_root)`` changes the bound project, the session MUST rebuild ``deps.skill_registry`` from the new project root so that project-level skills in the new project take effect on subsequent REPL turns. The rebuild MUST go through a new ``EngineDeps.rebind_skill_registry(new)`` method symmetric to the existing ``rebind_tool_runtime`` / ``rebind_story_consultant`` methods.

#### Scenario: set_project_root rebuilds the registry
- **WHEN** ``session.set_project_root(new_root)`` is called with a different path than the current ``project_root``
- **THEN** ``session.deps.skill_registry.get("/大纲")`` (after the call) MUST reflect the skills visible in the new project
- **AND** the registry MUST be a different object than before the call

#### Scenario: Same project_root is a no-op
- **WHEN** ``session.set_project_root(current_root)`` is called with the same path
- **THEN** the call MUST return without rebuilding the registry
- **AND** ``session.deps.skill_registry`` MUST be the same object as before the call

#### Scenario: EngineDeps exposes rebind_skill_registry
- **WHEN** a consumer inspects the ``EngineDeps`` Protocol
- **THEN** the Protocol MUST declare a ``rebind_skill_registry(new: SkillRegistry) -> EngineDeps`` method
- **AND** the production ``_DefaultEngineDeps`` MUST implement it using ``dataclasses.replace(self, skill_registry=new)`` (symmetric to the existing rebind methods)

### Requirement: built_skill_registry accepts project_root

``built_skill_registry`` MUST accept an optional ``project_root: Path | None = None`` parameter. When provided, the function MUST include ``discover_project_skills(project_root)`` in the assembled registry between the built-in layer and the entry-point layer.

#### Scenario: project_root=None matches legacy behavior
- **WHEN** ``built_skill_registry()`` is called without arguments
- **THEN** the resulting registry MUST contain only built-in skills and entry-point plugins
- **AND** no project-level skills MUST be added

#### Scenario: project_root given adds the project layer
- **WHEN** ``built_skill_registry(project_root=tmp_path)`` is called and ``tmp_path/.writer/skills/`` contains a valid skill
- **THEN** the resulting registry MUST contain that project-level skill
- **AND** the project-level skill MUST shadow any built-in with the same command

#### Scenario: built_skill_registry is wired into production_deps
- **WHEN** ``EngineSession.__post_init__`` builds the initial ``EngineDeps``
- **THEN** the session MUST pass its ``project_root`` to ``built_skill_registry`` so the initial registry already reflects the bound project
