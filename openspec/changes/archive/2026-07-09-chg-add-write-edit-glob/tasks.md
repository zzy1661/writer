# tasks: safe_write_file / safe_edit_file / safe_glob

## 1.1 ToolRuntime 新字段

- [x] `src/writer/tools/runtime.py` 加 module-level `DEFAULT_WRITE_WHITELIST` 常量
- [x] `ToolRuntime.__init__` 加 keyword-only `allowed_write_paths: frozenset[str] | None = None`
- [x] `self.allowed_write_paths = allowed_write_paths or DEFAULT_WRITE_WHITELIST` 在 `__init__` 末尾赋值
- [x] docstring 标注 D2 决策点 + 提到 SAFE-WRITE-TOOLS-1

## 1.2 SafeWriteFile 实现

- [x] `src/writer/tools/builtin/file_tools.py` 加 `SafeWriteFile` class
  - `name = "safe_write_file"`
  - 中文 description
  - `run(self, runtime, *, path: str, content: str, mode: Literal["create", "overwrite", "append"] = "create", backup: bool = True)`
  - 流程：safe_path → whitelist check → AGENT.md guard → size check → atomic + backup → return ToolResult(metadata={...})
- [x] 私有 helper：`_atomic_write(target, content)`、``_backup_original(target, runtime)`、`_guard_agent_md(target, content, mode, runtime) -> str`
- [x] `__all__` 加 `SafeWriteFile`

## 1.3 SafeEditFile 实现

- [x] 同文件加 `SafeEditFile` class
  - `name = "safe_edit_file"`
  - `run(self, runtime, *, path: str, old_string: str, new_string: str, replace_all: bool = False, dry_run: bool = False, backup: bool = True)`
  - 流程：safe_path → whitelist check → read file → count matches → apply (or dry_run) → atomic + backup → return ToolResult(metadata={"diff": ..., "replace_count": N, ...})
- [x] 私有 helper：`_unified_diff(old_content, new_content, path)`、`_apply_edit(content, old_string, new_string, replace_all)`
- [x] `__all__` 加 `SafeEditFile`

## 1.4 SafeGlob 实现

- [x] 新文件 `src/writer/tools/builtin/glob_tools.py`：定义 `SafeGlob` class
  - `name = "safe_glob"`
  - `run(self, runtime, *, pattern: str, sort_by: Literal["name", "mtime"] = "name")`
  - 流程：safe_path → glob/rglob → 过滤 hidden → sort → return ToolResult

## 1.5 builtin 注册

- [x] `src/writer/tools/builtin/__init__.py::built_tool_registry()` 注册 `SafeWriteFile() / SafeEditFile() / SafeGlob()`
- [x] `__all__` 加 3 个新 class

## 1.6 shipped SKILL.md 修对

- [x] `_shipped/续写/SKILL.md` L29：移除"通过 Bash 调 cat"那段；改为 `safe_write_file(mode="append")` 准确描述
- [x] `_shipped/改/SKILL.md` L30-31：in-place 改为 `safe_edit_file(old_string, new_string)`；完全重写 `safe_write_file(mode="overwrite")`；diff 路径走 dry_run 流程

## 1.7 state.py 暴露 CURRENT_STATE_SECTION_HEADER 常量

- [x] `src/writer/project/state.py` 加 module-level `CURRENT_STATE_SECTION_HEADER = "## 当前状态"`
- [x] 替换 `state.py` 内部所有硬编码 `"## 当前状态"` 字面量（grep 确认无残留）
- [x] AGENT.md guard 引用此常量（避免双份字面量）

## 1.8 测试

- [x] `tests/test_tools.py` 加 21 个新 test（write 7 + AGENT.md guard 4 + edit 5 + glob 4 + runtime 3，超出原计划 18 个，含 `_seed_manuscript` fixture + runtime 字段测试）
- [x] 测试 AGENT.md guard 时 mock 一个 AGENT.md 含题材行，验证 genre 被保留

## 1.9 验证

- [x] `uv run ruff check src tests` clean
- [x] `uv run mypy src/writer` clean
- [x] `uv run pytest -x --tb=short` 全过（基线 320 + 新增 33 = 353 ✓）
- [x] `openspec validate chg-add-write-edit-glob --strict` 通过
- [x] e2e 冒烟：`printf "/大纲 测试" | .venv/bin/writer --cd ./测试项目` —— LLM 应能调 `safe_write_file` 写 `outline/大纲.md`（需 WRITER_API_KEY 配置；无 key 走 placeholder 路径不验证 tool 调用）
- [x] `grep "safe_write_file\|safe_edit_file\|safe_glob" src/writer/tools/builtin/` 确认 3 个 tool 都注册

## 1.10 文档

- [x] `docs/技术架构总览.md` §三 Tool 段落补 9 个 builtin tool 列表（之前是 6 个）
- [x] `MEMORY.md` `## 验证基线` 段更新（tool 数 6 → 9，test 数基线更新）

## 依赖

- 1.1 必须在 1.2/1.3/1.4 之前（字段不存在）
- 1.7 可以和 1.2 并行
- 1.5 在 1.2/1.3/1.4 完成后
- 1.8 在 1.2/1.3/1.4 完成后
- 1.9 在 1.5 + 1.8 + 1.6 + 1.10 完成后