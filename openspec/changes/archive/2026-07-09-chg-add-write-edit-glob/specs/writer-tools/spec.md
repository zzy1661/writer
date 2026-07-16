# Capability: writer-tools

## Purpose

Builtin tool registry 的契约层：3 个新增 tool（`safe_write_file` / `safe_edit_file` / `safe_glob`）补齐 LLM tool loop 的"读 / 写 / 编辑 / 列表"四件套，与 Claude Code 的 Read / Write / Edit / Glob 对齐。配套的 `ToolRuntime.allowed_write_paths` 字段让上层（CLI / 测试 / 高级用户配置）可调路径白名单。

## ADDED Requirements

### Requirement: safe_write_file 三种 mode + 默认 create

The system SHALL provide `safe_write_file` as a builtin Tool in `src/writer/tools/builtin/file_tools.py`. Its `run()` signature MUST accept `path`, `content`, `mode: Literal["create", "overwrite", "append"] = "create"`, `backup: bool = True`.

#### Scenario: default mode is create, refuses to overwrite existing file
- **WHEN** a caller invokes `safe_write_file(path="manuscript/ch1.md", content="...")` against a project_root where `manuscript/ch1.md` already exists
- **THEN** the tool MUST raise `ToolDeniedError` containing "文件已存在" or "mode=overwrite"
- **AND** the file on disk MUST be unchanged

#### Scenario: mode=overwrite replaces atomically and creates a backup
- **WHEN** a caller invokes `safe_write_file(path="outline/大纲.md", content="...", mode="overwrite", backup=True)` against an existing file
- **THEN** the file at `outline/大纲.md` MUST contain exactly `content`
- **AND** a backup MUST exist at `.writer/backups/outline/大纲.md.<ISO-timestamp>`
- **AND** the write MUST be atomic (write to `.tmp.<uuid>` then `os.replace`)
- **AND** `ToolResult.metadata` MUST include `bytes_written`, `mode`, `mtime`, `sha256_first8`, `backup_path`

#### Scenario: mode=append skips atomic and backup
- **WHEN** a caller invokes `safe_write_file(path="manuscript/ch1.md", content="\n\n## 新段落", mode="append")`
- **THEN** `content` MUST be appended to the end of `manuscript/ch1.md`
- **AND** no backup MUST be created
- **AND** no `.tmp.*` file MUST remain

#### Scenario: content larger than max_file_size is rejected
- **WHEN** a caller invokes `safe_write_file(path="manuscript/big.md", content=<len > max_file_size>)`
- **THEN** the tool MUST raise `ToolOutputTooLargeError`
- **AND** no file MUST be written

### Requirement: safe_write_file enforces path whitelist via ToolRuntime

The system SHALL have `safe_write_file` check that the resolved path's first segment (relative to `project_root`) is in `runtime.allowed_write_paths`. The default whitelist SHALL be: `{"manuscript", "outline", "characters", "world", "notes", "创意", ".writer/cache", ".writer/agents"}`.

#### Scenario: write inside manuscript/ is allowed
- **WHEN** a caller invokes `safe_write_file(path="manuscript/ch1.md", content="...")`
- **THEN** the tool MUST succeed (modulo other constraints like size)

#### Scenario: write outside whitelist is rejected
- **WHEN** a caller invokes `safe_write_file(path="secrets/api_key.txt", content="...")` and "secrets" is NOT in the default whitelist
- **THEN** the tool MUST raise `ToolDeniedError` containing "whitelist" or "not allowed"
- **AND** no file MUST be created

#### Scenario: caller customizes whitelist via ToolRuntime
- **WHEN** `ToolRuntime(allowed_write_paths=frozenset({"custom_dir"}))` is constructed
- **THEN** subsequent `safe_write_file(path="custom_dir/foo.txt", ...)` calls MUST succeed
- **AND** `safe_write_file(path="manuscript/foo.txt", ...)` MUST fail (not in custom whitelist)

### Requirement: safe_write_file AGENT.md guard

The system SHALL have `safe_write_file` apply a 3-stage guard when `path` resolves to `AGENT.md`: (1) `mode` MUST be `overwrite`; (2) `content` MUST contain the literal `"## 当前状态"` section header; (3) if the existing `AGENT.md` contains a `题材: <genre>` line and the new content does NOT, the tool MUST merge the existing genre line into the new content before writing.

#### Scenario: AGENT.md mode=create is rejected
- **WHEN** a caller invokes `safe_write_file(path="AGENT.md", content="...", mode="create")` against a project_root where AGENT.md does NOT exist
- **THEN** the tool MUST raise `ToolDeniedError` explaining AGENT.md only allows overwrite

#### Scenario: AGENT.md mode=append is rejected
- **WHEN** a caller invokes `safe_write_file(path="AGENT.md", content="## 补丁", mode="append")`
- **THEN** the tool MUST raise `ToolDeniedError`

#### Scenario: AGENT.md content missing "## 当前状态" is rejected
- **WHEN** a caller invokes `safe_write_file(path="AGENT.md", content="# 全是自由内容", mode="overwrite")`
- **THEN** the tool MUST raise `ToolDeniedError` mentioning the missing section

#### Scenario: AGENT.md write preserves existing genre line
- **WHEN** the existing AGENT.md contains `- 题材: 历史` and a caller invokes `safe_write_file(path="AGENT.md", content="# 全新结构\n\n## 当前状态\n\n- state: S2\n", mode="overwrite")` (no 题材 line in new content)
- **THEN** the file written MUST contain `- 题材: 历史` preserved from the original
- **AND** `ToolResult.metadata["preserved_genre"]` MUST equal "历史"
- **AND** `ToolResult.metadata["genre_guard_triggered"]` MUST be `True`

### Requirement: safe_edit_file Claude Code Edit semantics

The system SHALL provide `safe_edit_file` as a builtin Tool with `run(*, path, old_string, new_string, replace_all: bool = False, dry_run: bool = False, backup: bool = True)`. Semantics MUST match Claude Code's Edit tool: exact string replacement with uniqueness check.

#### Scenario: unique old_string is replaced once
- **WHEN** a caller invokes `safe_edit_file(path="manuscript/ch1.md", old_string="原句", new_string="新句")` where "原句" appears exactly once
- **THEN** the file MUST contain "新句" in place of "原句"
- **AND** the rest of the file MUST be unchanged
- **AND** `ToolResult.metadata["replace_count"]` MUST equal 1

#### Scenario: ambiguous old_string without replace_all raises
- **WHEN** a caller invokes `safe_edit_file(path="manuscript/ch1.md", old_string="常用词", new_string="新词", replace_all=False)` where "常用词" appears 3 times
- **THEN** the tool MUST raise `ToolDeniedError` containing "3" or "replace_all"

#### Scenario: replace_all=True replaces every occurrence
- **WHEN** a caller invokes `safe_edit_file(path="manuscript/ch1.md", old_string="常用词", new_string="新词", replace_all=True)` where "常用词" appears 3 times
- **THEN** the file MUST contain "新词" in all 3 locations
- **AND** `ToolResult.metadata["replace_count"]` MUST equal 3

#### Scenario: old_string not found raises
- **WHEN** a caller invokes `safe_edit_file(path="manuscript/ch1.md", old_string="不存在的字符串", new_string="新")`
- **THEN** the tool MUST raise `ToolDeniedError` containing "未找到" or "not found"

#### Scenario: dry_run returns diff without writing
- **WHEN** a caller invokes `safe_edit_file(path="manuscript/ch1.md", old_string="原", new_string="新", dry_run=True)`
- **THEN** the file on disk MUST be unchanged
- **AND** `ToolResult.metadata["diff"]` MUST contain unified-diff-formatted text
- **AND** `ToolResult.metadata["dry_run"]` MUST be `True`

### Requirement: safe_glob pattern-based recursive listing

The system SHALL provide `safe_glob` as a builtin Tool with `run(*, pattern: str, sort_by: Literal["name", "mtime"] = "name")`. Pattern syntax MUST follow Python `pathlib.Path.glob` (non-recursive by default; `**` prefix for recursive).

#### Scenario: top-level pattern matches immediate children only
- **WHEN** a caller invokes `safe_glob(pattern="*.md")` against a project_root with `a.md` and `sub/b.md`
- **THEN** the result MUST include `a.md` only (not `sub/b.md`)
- **AND** `metadata["paths"]` MUST equal `["a.md"]`

#### Scenario: recursive pattern matches all descendants
- **WHEN** a caller invokes `safe_glob(pattern="**/*.md")` against the same project_root
- **THEN** the result MUST include `a.md` AND `sub/b.md`
- **AND** `metadata["paths"]` MUST equal `["a.md", "sub/b.md"]`

#### Scenario: sort_by=mtime returns newest first
- **WHEN** a caller invokes `safe_glob(pattern="manuscript/*.md", sort_by="mtime")` where `ch1.md` is older than `ch2.md`
- **THEN** the result MUST list `ch2.md` before `ch1.md`
- **AND** `metadata["paths"]` MUST equal `["manuscript/ch2.md", "manuscript/ch1.md"]`

#### Scenario: hidden files skipped
- **WHEN** a caller invokes `safe_glob(pattern="**/*")` and the project_root contains `.DS_Store` and `foo.md`
- **THEN** the result MUST include `foo.md` only
- **AND** `.DS_Store` MUST NOT appear

### Requirement: ToolRuntime exposes allowed_write_paths for customization

The system SHALL have `ToolRuntime.__init__` accept keyword-only `allowed_write_paths: frozenset[str] | None = None`. When `None`, the runtime MUST use `DEFAULT_WRITE_WHITELIST` from `src/writer/tools/runtime.py`.

#### Scenario: default whitelist is applied when None
- **WHEN** `ToolRuntime(project_root=root)` is constructed with no `allowed_write_paths`
- **THEN** `runtime.allowed_write_paths` MUST equal `DEFAULT_WRITE_WHITELIST`

#### Scenario: explicit frozenset is preserved
- **WHEN** `ToolRuntime(project_root=root, allowed_write_paths=frozenset({"custom"}))` is constructed
- **THEN** `runtime.allowed_write_paths` MUST equal `frozenset({"custom"})`

#### Scenario: production_deps uses default whitelist
- **WHEN** `production_deps(project_root=root)` is called
- **THEN** the returned `EngineDeps.tool_runtime.allowed_write_paths` MUST equal `DEFAULT_WRITE_WHITELIST`