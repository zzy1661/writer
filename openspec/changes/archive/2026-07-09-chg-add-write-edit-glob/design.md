# design: safe_write_file / safe_edit_file / safe_glob

## Context

writer-agent 的 4 个 shipped Markdown directive（`/大纲` `/目录` `/续写` `/改`，per `chg-markdown-skills`）描述的 LLM 工具流与实际 builtin registry 脱节。修复路径是补 3 个 tool：

| Tool | 替代谁 |
|---|---|
| `safe_write_file` | Python 内部 `Path.write_text`（多处硬编码） |
| `safe_edit_file` | 写作场景下"修订"的字符串替换原语 |
| `safe_glob` | `safe_list_dir` 不能 pattern 匹配的盲区 |

补完后，`engine/loop.py::_run_directive` 的 LLM tool loop 把 `safe_write_file` 等暴露给模型，4 个 SKILL.md 真正可跑。

## Goals

1. **打通 LLM → file 写入管道**：4 个 shipped directive 描述的 tool 流不再 broken
2. **多层安全兜底**：whitelist + atomic + backup + AGENT.md guard 防止 LLM 误操作毁项目
3. **Claude Code 语义对齐**：`safe_edit_file` 走精确字符串替换（与 Claude Code Edit 一致），降低 LLM prompt 适配成本
4. **可扩展**：`allowed_write_paths` 字段让高级用户可调白名单；`ToolRuntime.require_shell()` 钩子保留

## Non-goals

（见 proposal.md，本节不重复）

## Decisions

### D1. safe_write_file 三个 mode + 默认 create

```python
def run(self, runtime, *, path: str, content: str,
        mode: Literal["create", "overwrite", "append"] = "create",
        backup: bool = True) -> ToolResult
```

- **create**（默认）：文件存在 → `ToolDeniedError("文件已存在，需要 mode=overwrite")`；最保守
- **overwrite**：原子替换；`backup=True` 时原文件 → `.writer/backups/<relpath>.<ISO 时间戳>`
- **append**：tail-add；跳过 atomic 写（append 本就非原子）和 backup（无意义）

**为何默认 create 而非 overwrite**：LLM 倾向"保险一点"，默认 create 强制它显式承认"我要覆盖"。

### D2. 路径白名单（DEFAULT_WRITE_WHITELIST）

```python
# src/writer/tools/runtime.py
DEFAULT_WRITE_WHITELIST: frozenset[str] = frozenset({
    "manuscript",
    "outline",
    "characters",
    "world",
    "notes",
    "创意",
    ".writer/cache",
    ".writer/agents",
})
```

- **算法**：`path` 第一段（用 `Path.parts[0]`）必须在白名单内
  - ✅ `manuscript/chapter-1.md` → "manuscript" ∈ 白名单
  - ❌ `AGENT.md` → "" （parts[0] 是空字符串）不在白名单 → 默认拒绝；除非走 AGENT.md guard（见 D4）
  - ❌ `outline/../foo.md` → 先 `safe_path()` 解析 → 若解析后首段是 "outline" 通过；若逃逸到 project_root 外则 `safe_path` 拒绝
- **`ToolRuntime.allowed_write_paths=None` → 用 DEFAULT_WRITE_WHITELIST**
- **runtime.allowed_write_paths 是 frozenset[str]，None 表示用默认**

### D3. atomic write + backup

```python
# overwrite 模式
def _atomic_write(target: Path, content: str) -> None:
    tmp = target.with_suffix(target.suffix + f".tmp.{uuid4().hex[:8]}")
    try:
        tmp.write_text(content, encoding="utf-8")
        os.replace(tmp, target)  # POSIX 原子；Windows: 覆盖若是文件则原子
    except Exception:
        if tmp.exists():
            tmp.unlink()
        raise
```

**Backup 命名**：
- 旧文件存在 + mode=overwrite + backup=True → 先 `shutil.copy2` 到 `.writer/backups/<relpath>.<ISO8601>`
- ISO 格式：`2026-07-09T14-30-45` （冒号被某些 FS 拒绝，用 `-`）
- `.writer/backups/` 在 builtin 注册时若不存在，**首次调用时自动 mkdir**（仅 `mkdir(parents=True, exist_ok=True)`，不预先创建空目录）

### D4. AGENT.md guard（用户选 b）

```python
def _guard_agent_md(target: Path, content: str, mode: str, runtime: ToolRuntime) -> str:
    if target.name != "AGENT.md":
        return content  # 非 AGENT.md 不触发

    # Guard 1: 必须 overwrite
    if mode != "overwrite":
        raise ToolDeniedError(
            "AGENT.md 仅允许 mode=overwrite；create/append 会破坏元信息结构"
        )

    # Guard 2: 必须含 ## 当前状态 段（结构 sanity）
    if "## 当前状态" not in content:
        raise ToolDeniedError(
            "AGENT.md 必须包含 '## 当前状态' 段；如需新增状态字段请保留该段"
        )

    # Guard 3: 题材保留（防止 LLM 误删题材行）
    if target.exists():
        existing = target.read_text(encoding="utf-8")
        preserved_genre = _extract_genre_line(existing)
        if preserved_genre and preserved_genre not in content:
            # 把题材行插入到 content 的 ## 当前状态 段内
            content = _insert_genre_line(content, preserved_genre)
            # ToolResult.metadata["preserved_genre"] = preserved_genre
            # ToolResult.metadata["genre_guard_triggered"] = True

    return content
```

- `_extract_genre_line` / `_insert_genre_line` 复用 `state.py::read_genre_from_agent` 的正则 `r"^- 题材:\s*(.+)$"`，避免双份解析逻辑
- Guard 2 + Guard 3 让 LLM 不能"白纸重写" AGENT.md —— 必须保留结构 + 元信息

### D5. safe_edit_file 语义

```python
def run(self, runtime, *, path: str, old_string: str, new_string: str,
        replace_all: bool = False, dry_run: bool = False,
        backup: bool = True) -> ToolResult
```

| 情形 | 行为 |
|---|---|
| `old_string` 不在文件中 | raise `ToolDeniedError("未找到 old_string")` |
| `old_string` 出现 N≥2 次 + `replace_all=False` | raise `ToolDeniedError(f"找到 {N} 处匹配；显式传 replace_all=True")` |
| `old_string` 出现 N≥2 次 + `replace_all=True` | 全部替换；metadata.replace_count=N |
| `old_string` 出现 1 次 | 替换一次；metadata.replace_count=1 |
| `dry_run=True` | 计算 unified diff（含 + / - 行号），写入 metadata["diff"]；**不写文件**；metadata["dry_run"]=True |
| `dry_run=False`（默认） | atomic + backup + 实际写 |
| 文件不存在 | raise `ToolDeniedError("文件不存在，无法 edit")` |
| `old_string == new_string` | raise `ToolDeniedError("old_string == new_string，无修改")` |
| `old_string` 长度 > 文件 50% | 在 ToolResult.metadata 加 `large_edit_warning=True`（不阻止） |

### D6. safe_glob 语义

```python
def run(self, runtime, *, pattern: str, sort_by: Literal["name", "mtime"] = "name") -> ToolResult
```

| 情形 | 行为 |
|---|---|
| `pattern = "*.md"` | project_root.glob("*.md") — 仅顶层（不递归） |
| `pattern = "**/*.md"` | project_root.rglob("*.md") — 递归 |
| `pattern = "outline/*.md"` | project_root.glob("outline/*.md") — 单层 |
| 跳过 `.*` 开头的隐藏 | 一致 safe_list_dir |
| `sort_by="mtime"` | 按修改时间降序（最新优先，便于 /续写 找最新章节） |
| 无匹配 | output = "(无匹配)"，metadata.count=0 |

输出格式与 `safe_list_dir` 对齐：每行 `f <relpath>` 或 `d <relpath>`。递归时不区分 d/f，统一标 `f`（因为 glob 结果是文件列表）。

### D7. ToolRuntime 字段变更

```python
class ToolRuntime:
    def __init__(
        self,
        project_root: Path,
        *,
        shell_enabled: bool = False,
        max_file_size: int = 50_000,
        allowed_write_paths: frozenset[str] | None = None,  # NEW
    ) -> None:
        self.project_root = project_root.resolve()
        self.shell_enabled = shell_enabled
        self.max_file_size = max_file_size
        self.allowed_write_paths = allowed_write_paths or DEFAULT_WRITE_WHITELIST
```

- `None` → 默认白名单；调用方传 `frozenset({...})` 自定义
- `production_deps()` 不改 → 默认 None → 默认白名单
- 已有测试 `PlainDeps` stub / `_DefaultEngineDeps` 不破

### D8. SKILL.md 修对

```diff
# _shipped/续写/SKILL.md L29
- 4. 调 `safe_write_file`（通过 Bash 调 `cat >> file.md` 或类似）追加续写文本。
+ 4. 调 `safe_write_file(path=..., content=..., mode="append")` 在当前草稿末尾追加续写文本。
+    若 content 含章节完结标记（"<!-- CONTINUATION END -->"），改调 mode="create" 新建下一章文件。

# _shipped/改/SKILL.md L30-31
-    - in-place：用 `safe_write_file` 覆盖章节文件
-    - diff：写入 `manuscript/chapter-<chapter_id>.diff.md`
+    - in-place：用 `safe_edit_file(old_string=<原段>, new_string=<新段>)` 做精确替换；
+      若需要完全重写，改用 `safe_write_file(path=..., content=..., mode="overwrite")`。
+    - diff：先 dry_run 拿到 diff，让用户在 TextChunk 里确认；确认后改 dry_run=False 写。
+      旁路 diff 文件由用户显式选择（不在 SKILL.md 强制）。
```

不重写 SKILL.md 全文；只修描述不准确的 2 处。

### D9. langchain bridge 自动适配

无需改 `langchain_bridge.py`：`_build_args_schema` 用 `inspect.signature` 自动从 `run()` 提取参数（`path` / `content` / `mode` / `backup` / `dry_run` / `replace_all` / `old_string` / `new_string` / `pattern` / `sort_by`）→ Pydantic model。

**唯一约束**：`run()` 必须用 named keyword-only params（备忘 13；现有约定）。

### D10. 测试矩阵

```
tests/test_tools.py 新增 14 个:
  SAFE WRITE (7):
    - test_safe_write_file_creates_new_file
    - test_safe_write_file_create_mode_refuses_existing
    - test_safe_write_file_overwrite_creates_backup
    - test_safe_write_file_overwrite_no_backup_when_disabled
    - test_safe_write_file_append_skips_backup_and_atomic
    - test_safe_write_file_rejects_outside_whitelist
    - test_safe_write_file_rejects_oversize_content

  AGENT.MD GUARD (3):
    - test_safe_write_file_rejects_agent_md_with_mode_create
    - test_safe_write_file_agent_md_must_have_current_state_section
    - test_safe_write_file_agent_md_preserves_genre_when_missing

  SAFE EDIT (5):
    - test_safe_edit_file_replaces_unique_match
    - test_safe_edit_file_replace_all_when_multiple_matches
    - test_safe_edit_file_raises_when_old_string_missing
    - test_safe_edit_file_raises_when_old_string_ambiguous
    - test_safe_edit_file_dry_run_returns_diff_no_write

  SAFE GLOB (3):
    - test_safe_glob_matches_md_recursively
    - test_safe_glob_skips_hidden
    - test_safe_glob_sort_by_mtime

  共 18 个测试（拆细以提高失败定位精度）
```

## Risks

1. **LLM 误删全项目**：backup 默认开 + whitelist + atomic 4 层兜底；即便误删章节，`.writer/backups/` 留底可恢复
2. **atomic write 在 Windows 不完全原子**：`os.replace` 在 Windows 上若目标存在是原子的；若目标不存在则分两步（写 tmp → rename）—— Windows 上 rename 到不存在的目标也是原子的（NTFS）。Linux/macOS 全场景原子
3. **backup 目录膨胀**：长期写作项目 `.writer/backups/` 越来越大。本 change 不做清理（保留所有历史 backup）。如未来空间成问题，再加 `safe_cleanup_old_backups(keep_last_n=10)` 单独 change
4. **AGENT.md guard 误伤**：`## 当前状态` 是硬编码字符串检查；若未来 state.py 重构改了这字面量，guard 同步改（双方都引同一个常量更佳；本 change 在 state.py 暴露 `CURRENT_STATE_SECTION_HEADER = "## 当前状态"`，guard 引用它）
5. **`allowed_write_paths` 误配置**：用户传空 frozenset → 全部写入拒绝（fail-closed 优先）；fail-open 风险无
6. **dry_run 的 diff 输出可能很大**：unified diff 在大文件 + 大 new_string 时可能撑爆 LLM context。本 change 设阈值 `len(diff) > max_file_size // 2` 时降级为"diff 太长，请用 safe_write_file 全文覆盖"提示

## Migration

- ToolRuntime 新增 keyword-only param，**无 default 变更**（None = 默认白名单 = 旧行为）
- `production_deps()` 不改
- 已有 test_tools.py 测试不破
- AGENT.md guard 是纯加项（不在白名单外的路径已默认拒绝，AGENT.md 通过 guard 是显式开启的窄口）
- 7 个 shipped directive 不需要重写，只需修 2 处描述（见 D8）

## Open questions

- Q：是否要给 backup 加全局 max count？比如 `.writer/backups/` 超过 100 个就清理最老的。本 change 不做；留给 `chg-add-cleanup-tools`
- Q：safe_edit_file 是否需要支持"基于行号的精确替换"（如 old_line=42, replace 1 line）？本 change 不做；纯字符串语义，与 Claude Code Edit 对齐