## ADDED Requirements

### Requirement: Four shipped directives exist

The package MUST ship exactly four directives at ``src/writer/skills/_shipped/<command>/``:

* ``大纲/`` (``command: /大纲``, description: 生成或查看大纲)
* ``目录/`` (``command: /目录``, description: 生成或查看章节目录)
* ``续写/`` (``command: /续写``, description: 继续未完成章节)
* ``改/`` (``command: /改``, description: 修改章节内容)

Each MUST contain a ``SKILL.md`` and a ``references/`` subdirectory. ``scripts/`` is optional.

#### Scenario: Shipped directives are loadable
- **WHEN** ``built_directive_registry(project_root=None)`` is called
- **THEN** the registry MUST contain exactly four directives
- **AND** their commands MUST be ``["/大纲", "/目录", "/续写", "/改"]``

#### Scenario: Shipped directives are packaged with the wheel
- **WHEN** the package is built (``uv build`` or equivalent)
- **THEN** the resulting wheel MUST contain ``writer/skills/_shipped/大纲/SKILL.md`` and the other three
- **AND** ``importlib.resources.files("writer.skills._shipped")`` MUST resolve to a traversable path

### Requirement: Shipped SKILL.md frontmatter is valid YAML

Every shipped directive's ``SKILL.md`` MUST have a valid YAML frontmatter with three required fields: ``command``, ``description``, ``requires_states``.

#### Scenario: Frontmatter parses without error
- **WHEN** any shipped SKILL.md is read
- **THEN** the frontmatter MUST parse via ``yaml.safe_load`` without raising
- **AND** MUST contain ``command``, ``description``, ``requires_states`` keys

#### Scenario: requires_states lists real ProjectState values
- **WHEN** any shipped SKILL.md's ``requires_states`` is parsed
- **THEN** every value MUST be a valid member of the ``ProjectState`` enum
- **AND** MUST NOT contain strings like ``"S5"`` or other non-enum values

### Requirement: Shipped directive bodies follow a consistent template

Every shipped SKILL.md body MUST be structured as:

1. A short role statement ("你是...")
2. Inputs the LLM should read (specific project files)
3. The tool calls the LLM should make
4. The output file paths the LLM should write
5. Any constraints / edge cases

#### Scenario: Body describes the work to be done
- **WHEN** the shipped ``大纲/SKILL.md`` body is read
- **THEN** it MUST describe the steps for generating an outline
- **AND** MUST mention specific input files (e.g. ``outline/premise.md``)
- **AND** MUST mention specific output files (e.g. ``outline/大纲.md``)
- **AND** MUST mention refreshing ``AGENT.md`` after writing

#### Scenario: Body includes @reference references
- **WHEN** the shipped ``大纲/SKILL.md`` body references templates
- **THEN** it MUST use the ``@reference references/<file>`` syntax
- **AND** each referenced file MUST exist in the ``references/`` subdirectory

### Requirement: Shipped references are project-relevant Markdown documents

Every shipped directive's ``references/`` subdirectory MUST contain at least one ``*.md`` file with concrete, reusable content (templates, examples, style guides, format specs). Empty directories or stub files like ``README.md`` with a single line MUST NOT pass the shipped reference quality bar.

#### Scenario: 大纲 references include template and examples
- **WHEN** the shipped ``大纲/references/`` directory is read
- **THEN** it MUST contain a template file (e.g. ``4-act-template.md``)
- **AND** MUST contain an examples file (e.g. ``examples.md``)
- **AND** each file MUST be at least 500 bytes (real content, not a stub)

#### Scenario: Each directive has at least one reference
- **WHEN** any shipped directive's ``references/`` directory is enumerated
- **THEN** it MUST contain at least one ``*.md`` file
- **AND** the file MUST NOT be empty

### Requirement: Shipped directives are content-frozen

Shipped directives' files (``SKILL.md`` + ``references/`` + ``scripts/``) MUST NOT be modified at runtime by any code path. ``create_new_workspace`` copies them to the user's project; once copied, the user owns them.

#### Scenario: _shipped directory is read-only at runtime
- **WHEN** the engine processes a directive
- **THEN** it MUST NOT write to ``src/writer/skills/_shipped/<command>/``
- **AND** the directory MUST only be read for seeding the user's project

#### Scenario: Copy operation does not modify source
- **WHEN** ``create_new_workspace`` seeds directives into ``<project>/.writer/skills/``
- **THEN** the source files in ``_shipped`` MUST be byte-identical before and after
- **AND** the project's copies are independent files that the user can edit freely