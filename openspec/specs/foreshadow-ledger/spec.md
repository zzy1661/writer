# Capability: foreshadow-ledger

## Purpose

Project-local structured ledger for tracking foreshadowing (伏笔) entries across the writing process. Replaces the previous RAG-based fuzzy recall (which had near-zero precision on real Chinese queries). The ledger is a human-editable YAML file at `<project_root>/伏笔.yaml`; queries are deterministic in-memory filters with structured criteria (`id` / `tags` / `status` / `chapter_range` / `keyword`), all combining with AND. This is the file-system analog of a TTRPG "plot coupon" notebook: the writer plants and cashes entries by ID, the engine reads them deterministically.

## Requirements

### Requirement: Foreshadow ledger file schema

The system MUST define a project-local foreshadow ledger file at `<project_root>/伏笔.yaml` with the following schema:

```yaml
# 伏笔 ledger schema v1
foreshadows:
  - id: F001                # 字符串，匹配 ^F\d+$
    tags: [玉簪, 旧匣子]    # 字符串数组，可为空数组
    status: paid            # "laid" | "paid"
    laid_chapter: 3         # 整数 ≥ 1
    paid_chapter: 47        # 整数 ≥ 1，或 null（未回收）
    notes: 主角身世揭晓     # 字符串，可为空
```

The system MUST treat this file as optional: when it is absent or contains `foreshadows: []`, the ledger is considered empty and tools MUST return a "no records" response rather than raise an error.

#### Scenario: Valid ledger parses without error
- **WHEN** `<project_root>/伏笔.yaml` exists and contains a `foreshadows:` list with at least one entry matching the schema
- **THEN** `ForeshadowSearch.run(...)` MUST return a `ToolResult` containing the matching entry's `id` in its output

#### Scenario: Missing file is treated as empty ledger
- **WHEN** `<project_root>/伏笔.yaml` does not exist
- **THEN** `ForeshadowSearch.run(...)` MUST return `ToolResult(output="暂无伏笔记录，请先创建 伏笔.yaml 或在 /init 时生成")` without raising

#### Scenario: Empty foreshadows list is treated as empty ledger
- **WHEN** `<project_root>/伏笔.yaml` exists with `foreshadows: []`
- **THEN** `ForeshadowSearch.run(...)` MUST return the same "暂无伏笔记录" response as the missing-file case

#### Scenario: Schema-invalid file returns friendly error
- **WHEN** `<project_root>/伏笔.yaml` exists but lacks the `foreshadows` key, or contains entries missing required fields (`id`, `tags`, `status`, `laid_chapter`, `paid_chapter`, `notes`)
- **THEN** `ForeshadowSearch.run(...)` MUST return `ToolResult(output=<error message>, metadata={"error": "schema"})` and MUST NOT raise an exception

### Requirement: ForeshadowSearch tool signature

The system MUST provide a tool named `foreshadow_search` (registered in `writer.tools.builtin`) that queries the ledger. The tool MUST be discoverable via `ToolRegistry.describe()` so LLM tool loops can call it.

The tool's `run()` method MUST accept the following keyword-only arguments:

| Argument | Type | Default | Meaning |
| --- | --- | --- | --- |
| `id` | `str \| None` | `None` | Exact `F\d+` lookup |
| `tags` | `list[str] \| None` | `None` | Match if entry's `tags` contains ANY of the given tags (OR semantics) |
| `status` | `Literal["laid","paid","all"]` | `"all"` | Filter by ledger status |
| `chapter_range` | `tuple[int,int] \| None` | `None` | Restrict to entries with `laid_chapter` in the inclusive range |
| `keyword` | `str \| None` | `None` | Substring match against `id` / `tags` / `notes` fields (case-sensitive) |

#### Scenario: Lookup by id returns single entry
- **WHEN** `ForeshadowSearch.run(runtime, id="F003")` is called and the ledger contains entry `id: F003`
- **THEN** the returned `ToolResult.output` MUST include that entry's full record (id, tags, status, laid_chapter, paid_chapter, notes)
- **AND** MUST include exactly one entry

#### Scenario: Filter by status=laid excludes paid entries
- **WHEN** `ForeshadowSearch.run(runtime, status="laid")` is called on a ledger with a mix of laid and paid entries
- **THEN** the returned entries MUST all have `status="laid"`
- **AND** MUST NOT include any entry with `status="paid"`

#### Scenario: Filter by status=paid returns only paid entries
- **WHEN** `ForeshadowSearch.run(runtime, status="paid")` is called
- **THEN** the returned entries MUST all have `status="paid"`

#### Scenario: Filter by status=all returns everything
- **WHEN** `ForeshadowSearch.run(runtime, status="all")` is called
- **THEN** the returned entries MUST include both laid and paid entries

#### Scenario: Filter by tag matches any of given tags
- **WHEN** `ForeshadowSearch.run(runtime, tags=["玉簪", "身世"])` is called
- **THEN** the returned entries MUST have at least one of "玉簪" or "身世" in their `tags` array

#### Scenario: Filter by chapter_range restricts laid_chapter
- **WHEN** `ForeshadowSearch.run(runtime, chapter_range=(10, 20))` is called
- **THEN** the returned entries MUST have `laid_chapter` in the inclusive range `[10, 20]`

#### Scenario: Keyword substring matches id, tags, or notes
- **WHEN** `ForeshadowSearch.run(runtime, keyword="玉簪")` is called
- **THEN** the returned entries MUST have "玉簪" appearing as a substring in at least one of: `id`, any element of `tags`, or `notes`

#### Scenario: Multiple filters combine with AND
- **WHEN** `ForeshadowSearch.run(runtime, tags=["玉簪"], status="laid", chapter_range=(1, 10))` is called
- **THEN** the returned entries MUST satisfy all three conditions simultaneously

### Requirement: ForeshadowSearch tool is path-free and project-root-aware

`ForeshadowSearch` MUST be a path-free tool: it does NOT receive a `path` argument. It locates the ledger at `<runtime.project_root>/伏笔.yaml` automatically. When `runtime.project_root is None`, the tool MUST return a `ToolResult` indicating the missing project root without raising.

#### Scenario: Project root None returns error result
- **WHEN** `ForeshadowSearch.run(runtime, ...)` is called with `runtime.project_root is None`
- **THEN** the tool MUST return `ToolResult(output=<error message>, metadata={"error": "no_project_root"})` and MUST NOT raise

#### Scenario: Path traversal is not possible
- **WHEN** any argument that could be interpreted as a path (e.g. `id="../../etc/passwd"`) is passed
- **THEN** the tool MUST treat it as a literal id (or substring) and MUST NOT perform any file access outside `<runtime.project_root>/伏笔.yaml`
