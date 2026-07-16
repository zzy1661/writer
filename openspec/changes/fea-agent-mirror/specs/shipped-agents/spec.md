# Capability: shipped-agents (delta: ADDED)

## ADDED Requirements

The 4 built-in agents shipped at `src/writer/agents/_shipped/<name>.md` (per `fea-agent-mirror`). These are the only agents the project provides out of the box; everything else is user-added or via entry-point plugins. After `create_new_workspace` (`writer new`) copies them into `<project_root>/.writer/agents/`, the project's copies are byte-identical to the shipped source and the user owns them — there is no behavioral distinction between shipped and user-added agents in the discovery / registry layers.

The capability defines a content-freeze contract: shipped source files are read-only at runtime; only `create_new_workspace` may copy them, and the copies are independent files.

The format mirrors Claude Code `.claude/agents/architecture-optimizer.md` (YAML frontmatter + markdown body) so the project adopts the same authoring surface users already know from Claude Code. The body becomes the agent's system prompt at LLM call time; the frontmatter `description:` is the field the parent LLM reads to decide whether to dispatch to this agent.

### Requirements

### Requirement: Four shipped agents exist

The package MUST ship exactly four agents at `src/writer/agents/_shipped/<name>.md`:

* `other.md` (name: `other`, genre: `other`, description: 兜底题材编剧；中性四幕结构) — the default fallback
* `历史.md` (name: `history`, genre: `历史`, description: 历史题材编剧；专长把虚构人物嵌入真实朝代与历史事件)
* `言情.md` (name: `romance`, genre: `言情`, description: 言情题材编剧；专长以情感节拍 + GMC 结构推进)
* `玄幻.md` (name: `xuanhuan`, genre: `玄幻`, description: 玄幻题材编剧；专长以境界推进 + 副本叙事)

#### Scenario: Shipped agents are loadable
- **WHEN** `builtin_agent_registry()` is called
- **THEN** the registry MUST contain exactly four agents
- **AND** their names MUST be `["history", "other", "romance", "xuanhuan"]` (sorted alphabetically)

#### Scenario: Shipped agents are packaged with the wheel
- **WHEN** the package is built (`uv build` or equivalent)
- **THEN** the resulting wheel MUST contain `writer/agents/_shipped/other.md` and the other three
- **AND** `importlib.resources.files("writer.agents._shipped")` MUST resolve to a traversable path

### Requirement: Shipped agent frontmatter is valid YAML

Every shipped agent's `.md` MUST have a valid YAML frontmatter with three required fields: `name`, `description`, `genre`.

#### Scenario: Frontmatter parses without error
- **WHEN** any shipped `.md` is read
- **THEN** the frontmatter MUST parse via `yaml.safe_load` without raising
- **AND** MUST contain `name`, `description`, `genre` keys
- **AND** `name` MUST be a non-empty string matching `^[a-z][a-z0-9_]*$`
- **AND** `description` MUST be a non-empty string between 50 and 500 characters
- **AND** `genre` MUST be one of `{"other", "历史", "言情", "玄幻"}`

#### Scenario: Body is non-empty markdown
- **WHEN** any shipped `.md` body is read (text after the closing `---` of the frontmatter)
- **THEN** the body MUST be non-empty
- **AND** the body MUST be valid UTF-8

### Requirement: Shipped agent descriptions are LLM-dispatch-ready

Every shipped agent's `description` field MUST be a single-paragraph (or 2-3 short sentences) natural-language statement that lets the parent LLM decide "is this the right agent for this user input?". The description MUST mention at least one concrete trigger scenario (e.g. "适合处理「朝代背景」「年表顺序」类任务") and at least one non-scenario (what the agent is NOT for, to help the LLM disambiguate).

#### Scenario: Description names 3+ trigger scenarios
- **WHEN** any shipped agent's `description` is read
- **THEN** it MUST name at least 3 concrete trigger scenarios
- **AND** it MUST be in Simplified Chinese (matching the rest of the project's user-facing strings)

#### Scenario: Description is distinguishable across agents
- **WHEN** all 4 shipped agents' descriptions are read side-by-side
- **THEN** the parent LLM (or a human reviewer) MUST be able to tell which agent fits "朝代背景 / 历史考证" input, which fits "情感节拍 / 关系推进", etc.
- **AND** no two agents MAY have identical `description` text

### Requirement: writer new mirrors 4 shipped agents to the project

`create_new_workspace` (the `writer new` path) MUST copy all 4 shipped `.md` files to `<project_root>/.writer/agents/<filename>` byte-identically.

#### Scenario: writer new creates 4 agent files
- **WHEN** `create_new_workspace(name, base_dir)` runs on a fresh directory
- **THEN** `<root>/.writer/agents/{other,历史,言情,玄幻}.md` MUST all exist
- **AND** their content MUST be byte-identical to the shipped `_shipped/` source (sha256 match)

#### Scenario: create_workspace (low-level) does NOT seed agents
- **WHEN** `create_workspace(name, base_dir, with_writer_meta=True)` is called (the low-level API, NOT `create_new_workspace`)
- **THEN** `<root>/.writer/agents/*.md` MUST NOT be created
- **AND** `<root>/.writer/agents/.gitkeep` MUST remain the only content (if it was the placeholder)

#### Scenario: re-running writer new does not overwrite user edits
- **WHEN** a project already has `<root>/.writer/agents/历史.md` (modified by the user) and `writer new <name> --force` is run
- **THEN** existing agent files MUST be left untouched (no overwrite)
- **AND** missing agent files MUST be backfilled from shipped source
- **AND** a log WARNING MUST be emitted if the existing file's sha256 differs from the shipped source (drift detected)

### Requirement: AgentRegistry last-write-wins

`AgentRegistry` MUST apply last-write-wins semantics: when both a built-in agent and a project-level agent share the same `name`, the project-level agent takes precedence. Duplicate names within the same scope (e.g. two project-level agents both named "history") MUST raise `AgentRegistryError` at registry construction time.

#### Scenario: Project agent overrides built-in
- **WHEN** `built_agent_registry(project_root=<root>)` is called and `<root>/.writer/agents/历史.md` exists with the same `name: history` as the built-in
- **THEN** the registry MUST contain the project-level agent (not the built-in)
- **AND** `.require("history")` MUST return the project-level agent's body / description

#### Scenario: Duplicate name within project raises
- **WHEN** `<root>/.writer/agents/` contains two files with the same `name:` field
- **THEN** `built_agent_registry(project_root=<root>)` MUST raise `AgentRegistryError` listing both conflicting file paths

#### Scenario: Built-in only fallback for legacy projects
- **WHEN** a project was created before `fea-agent-mirror` shipped (no `.writer/agents/` directory at all)
- **THEN** `built_agent_registry(project_root=<root>)` MUST return a registry containing only the 4 built-in agents
- **AND** MUST NOT raise (the absence of the project directory is not an error)

### Requirement: AgentRegistry provides LLM-facing description list

`AgentRegistry.descriptions()` MUST return a list of `{name, description, genre}` dicts suitable for injection into the LLM's system prompt during routing. Each description MUST be truncated to ≤ 200 characters; the total list MUST be capped at 16 agents (truncating with a log WARNING if exceeded, to prevent prompt explosion).

#### Scenario: descriptions() output shape
- **WHEN** `AgentRegistry([Agent(name="history", description="..." * 300, genre="历史", body="..."), ...]).descriptions()` is called
- **THEN** the returned list MUST contain `{"name": "history", "description": "<truncated to 200 chars>", "genre": "历史"}` for each agent
- **AND** the original `Agent` objects MUST NOT be mutated (descriptions is a read view)

#### Scenario: descriptions() caps at 16 agents
- **WHEN** the registry contains 20 agents
- **THEN** `descriptions()` MUST return exactly 16 items
- **AND** a log WARNING MUST be emitted noting "agent descriptions truncated from 20 to 16"

### Requirement: Built-in agent source drift detection

`BUILTIN_AGENT_SOURCES` MUST record the sha256 of each shipped `.md`. At registry construction time, if a shipped source's sha256 does not match the recorded value, a log WARNING MUST be emitted (the agent is still loaded — drift is a soft warning, not an error).

#### Scenario: Drift detected on tampered shipped source
- **WHEN** `_check_builtin_sources_drift()` is called and `src/writer/agents/_shipped/历史.md` was modified after the BUILTIN_AGENT_SOURCES sha was recorded
- **THEN** a log WARNING MUST be emitted naming the file and the expected vs actual sha
- **AND** the registry MUST still load the (drifted) file (no hard failure)

#### Scenario: No drift on pristine shipped source
- **WHEN** all shipped `.md` files match their recorded sha256
- **THEN** `_check_builtin_sources_drift()` MUST NOT emit any log message
