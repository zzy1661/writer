# fea: 新增 safe_write_file / safe_edit_file / safe_glob 三个 builtin tool

## Why

writer-agent 当前 builtin tool registry 只有 6 个 tool，**0 个写入能力**。然而刚上线的 4 个 shipped Markdown directive（`/大纲` `/目录` `/续写` `/改`，per `chg-markdown-skills`）的 SKILL.md body 里**已经在描述**"调 `safe_write_file`" / "调 `safe_edit_file`"：

- `_shipped/大纲/SKILL.md` L25-29：read existing, then 写入 `outline/大纲.md`
- `_shipped/目录/SKILL.md` L24-26：read outline, then 写入 `outline/toc.md`
- `_shipped/续写/SKILL.md` L29：调 `safe_write_file`（通过 Bash 调 `cat >> file.md` 或类似）追加续写文本
- `_shipped/改/SKILL.md` L30-31：用 `safe_write_file` 覆盖章节文件 / 写入 diff 旁路

`engine/loop.py:464-465` 的 docstring 同样提及 `safe_write_file`，但 builtin registry 里**没有这个 tool**。结果是：

1. LLM 在 `_run_directive` 跑 SKILL.md 时，`deps.tool_loop.run` 把指令喂给 LLM，LLM 收到一份 tool 目录（`describe()`）—— **目录里没有 safe_write_file**，于是 LLM 卡住
2. 实际写入全部走 Python 内部硬编码（`project/state.py:350` `agent_md.write_text(...)`、`workspace.py` 等），SKILL.md 描述的"L 调 tool"流程完全 broken
3. `tools/runtime.py:47-50` 已留好 `require_shell()` 钩子（`shell_enabled=False` 默认），作者显然预设过 shell_exec 类工具路径，但未落地

加 3 个 tool 把这条管道打通：

| Tool | 解决什么 | 服务哪些 SKILL.md |
|---|---|---|
| `safe_write_file` | 创建/覆盖/追加 Markdown 文件 | 大纲、目录、续写、改 |
| `safe_edit_file` | Claude Code Edit 风格的字符串精确替换 | 改 |
| `safe_glob` | pattern 匹配的递归列表 | 续写（找最新章节）、目录（找全部章） |

## What Changes

### 新增 builtin tool

- `src/writer/tools/builtin/file_tools.py`：新增 `SafeWriteFile` / `SafeEditFile` 两个 class（与 `SafeReadFile` / `SafeListDir` 同文件）
- `src/writer/tools/builtin/glob_tools.py`（新文件）：`SafeGlob` class

### ToolRuntime 新字段

- `src/writer/tools/runtime.py`：`ToolRuntime.__init__` 新增 keyword-only `allowed_write_paths: frozenset[str] | None = None`；`None` → 使用 module-level 常量 `DEFAULT_WRITE_WHITELIST`
- `DEFAULT_WRITE_WHITELIST` = `frozenset({"manuscript", "outline", "characters", "world", "notes", "创意", ".writer/cache", ".writer/agents"})`

### 注册

- `src/writer/tools/builtin/__init__.py::built_tool_registry()`：register `SafeWriteFile()` / `SafeEditFile()` / `SafeGlob()`，连同现有 6 个共 9 个
- `__all__` 同步更新

### AGENT.md 写入 guard

- `safe_write_file` 写入 `AGENT.md` 时强制 `mode=overwrite` 且 content 含 `## 当前状态` 段
- 写入前 read existing；若旧文件含 `题材: <genre>` 行且新 content 缺该行，**自动 merge**（复用 `state.py::read_genre_from_agent` 反向逻辑）—— 防止 LLM 误删题材元信息

### shipped SKILL.md 修对

- `_shipped/续写/SKILL.md` L29：移除"（通过 Bash 调 `cat >> file.md` 或类似）"那段误描述（暗示 Bash tool 存在，实际不存在）
- `_shipped/改/SKILL.md` L30-31：明确"in-place 用 `safe_edit_file`（`old_string`/`new_string`）/ 完全重写用 `safe_write_file(mode=overwrite)`"

### 测试

- `tests/test_tools.py`：新增 14 个 test（write 7 + edit 5 + glob 3，覆盖 happy path、whitelist 拒绝、backup 生成、atomic write 失败保留原文件、dry_run diff 模式、glob recursive + mtime sort）

## Non-goals (明确不做)

- **MultiEdit** (batch 字符串替换)：单 edit 已足够覆盖 4 个 shipped directive；如未来 `_shipped/改` 需要批量改人物名，再开 `chg-add-multi-edit`
- **Bash / shell_exec**：`ToolRuntime.require_shell()` 钩子保留作为未来扩展点；本 change 不实现 shell 类工具（写作场景下风险 > 收益；append 用 `mode=append` 安全替代）
- **WebFetch / WebSearch**：见 `chg-add-write-edit-glob` 后续 sprint，本 change 不动
- **safe_delete_file**：4 个 shipped directive 都不删文件；如未来需要清理 `.writer/cache/`，再开 `chg-add-cleanup-tools`
- **path whitelist 的 UI 配置**：本 change 仅暴露 `ToolRuntime.allowed_write_paths` Python API；`.writer/config` 的 YAML 注入留给后续
- **safe_edit_file 的 auto-format / syntax check**：纯字符串替换，不调 prettier / markdownlint

## Capabilities

### 新建 capability

- `writer-tools` —— builtin tool registry 的写 + 编辑 + glob 三件套契约

### 不动 capability

- `engine-loop` —— `_run_directive` 不改；只是 builtin registry 多 3 个 tool，tool loop 透传
- `shipped-skills` / `skill-directives` —— SKILL.md 文档小修
- `foreshadow-ledger` —— 无关
- `genre-init` —— AGENT.md guard 复用 `read_genre_from_agent`，不修改其行为

## Impact

| 维度 | 影响 |
|---|---|
| 新增文件 | `src/writer/tools/builtin/glob_tools.py` (1) + `tests/test_tools.py` 追加 (0 新文件) |
| 修改文件 | `src/writer/tools/builtin/file_tools.py` / `src/writer/tools/builtin/__init__.py` / `src/writer/tools/runtime.py` + 2 个 SKILL.md + 1 个 proposal 内 list |
| 新增 builtin tool 数 | 6 → 9 |
| 新增 test 数 | +14 |
| 向后兼容 | ✅ ToolRuntime.allowed_write_paths 默认 None；registry 自动 pick up；旧 test 不破 |
| 风险 | LLM 误删 / 误覆盖 → 靠 backup (默认开) + atomic write + whitelist + AGENT.md guard 4 层兜底 |