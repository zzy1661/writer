# Bug 04: 写入白名单字面值(`.writer/cache`)与匹配规则(`rel.parts[0]`)不一致

## 元信息

| 严重程度 | 🟠 Major |
|---|---|
| 状态 | 待修 |
| 发现日期 | 2026-07-09 |
| 关联文件 | `src/writer/tools/builtin/file_tools.py:101-119`、`src/writer/tools/runtime.py:18-29`、`docs/技术架构总览.md:278`、`备忘 13-核心Tool设计.md:54-95`、`openspec/specs/writer-tools/spec.md:36` |
| 测试盲区 | fixture 全用顶层目录(`manuscript/...`),从未构造 `.writer/cache/x.md` |

## 1. 现象(Symptom)

### 可复现步骤

1. 启动 REPL + `/init` 创建项目,默认已生成 `.writer/cache/` 目录
2. LLM 工具循环尝试通过 `safe_write_file` 写 `.writer/cache/llm-state.md`
3. 实际结果:`ToolDeniedError: 写入路径 'llm-state.md' 不在白名单 ['.writer/agents', '.writer/cache', 'manuscript', 'characters', 'world', 'notes', 'outline', '创意'] 内`
4. 期望结果:写入成功,因为 `.writer/cache` 在白名单里

### 代码引用

```python
# src/writer/tools/runtime.py:18-29
DEFAULT_WRITE_WHITELIST: frozenset[str] = frozenset(
    {
        "manuscript", "outline", "characters", "world", "notes", "创意",
        ".writer/cache",      # ← 含路径前缀
        ".writer/agents",     # ← 含路径前缀
    }
)

# src/writer/tools/builtin/file_tools.py:101-119
def _check_whitelist(target: Path, runtime: ToolRuntime) -> None:
    rel = target.relative_to(runtime.project_root)
    first = rel.parts[0] if rel.parts else ""   # ← 只取第一段
    if first not in runtime.allowed_write_paths:
        raise ToolDeniedError(...)
```

## 2. 根因(Root Cause)

白名单数据与匹配规则语义不一致:`DEFAULT_WRITE_WHITELIST` 含完整路径前缀(`.writer/cache`、`'.writer/agents`),但 `_check_whitelist` 用 `Path.relative_to()` 后只取 `rel.parts[0]`(即最高一层目录名)。对于 `.writer/cache/foo.md`,`rel.parts = (".writer", "cache", "foo.md")`,`parts[0] = ".writer"`,而 `.writer` **不在**白名单里 → 误拒绝。

### 数据流图

```
target = project_root / ".writer/cache/llm-state.md"
        ↓ relative_to
rel.parts = (".writer", "cache", "llm-state.md")
        ↓ rel.parts[0]
first = ".writer"                          ← ✗ 与 ".writer/cache" 不匹配
        ↓ first not in whitelist          ← whitelist 含 ".writer/cache"
ToolDeniedError
```

**期望**:白名单 `.writer/cache` 应匹配 `rel.parts` 的前缀,即 `(".writer", "cache", ...)`,而 `rel.parts[0] = ".writer"` 仅匹配白名单里的 `.writer`(而该条目当前不存在)。

## 3. 影响范围(Blast Radius)

| 受影响表面 | 触发条件 | 严重性 | 当前绕过方式 |
|---|---|---|---|
| `safe_write_file` / `safe_edit_file` 写 `.writer/cache/*` | 任何 LLM 工具循环试图缓存中间状态、LLM scratchpad | 高(LLM 工具循环很可能需要缓存) | 用户手动从 REPL 改文件(绕过 Tool);无法自动化 |
| `safe_write_file` / `safe_edit_file` 写 `.writer/agents/*` | LLM 更新 project-level agent Markdown override(per `fea-agent-mirror`) | 高(整个 agent-mirror 体系崩溃) | 同样需手动改文件 |
| `safe_read_file` / `safe_list_dir` / `safe_glob` | **不受影响**(白名单仅约束写入) | — | — |
| 任意 path-segment 含 `.` 的顶层目录 | 任何未来扩展(如 `.config`、`/notes/...` 同名冲突) | 中 | 暂无 |

**注**:`.writer` 顶层目录在白名单中**没有对应条目**,因此即便白名单匹配规则改成前缀匹配,纯 `.writer/foo.md` 仍然被拒绝 — 这是设计上的预期(避免 LLM 写元数据根目录)。`AGENT.md` 通过 `_guard_agent_md` 三段守卫单独放行,与白名单独立。

## 4. 修复方案(Fix)

### 方案 A(★ 主推):升级到路径前缀匹配 + 统一扁平白名单

将白名单改成"任一祖先(包含自己)在白名单 → 允许"。这样 `.writer/cache/foo.md` 的祖先序列 `(".writer/cache", ".writer")` 中,`.writer/cache` 在白名单内即放行。

```python
# fix proposal — src/writer/tools/builtin/file_tools.py

def _check_whitelist(target: Path, runtime: ToolRuntime) -> None:
    try:
        rel = target.relative_to(runtime.project_root)
    except ValueError as err:
        raise ToolDeniedError(f"路径越界: {target}") from err

    if not rel.parts:
        # rel == project_root 自身,跳过检查,留给上层 AGENT.md guard
        return

    whitelist = runtime.allowed_write_paths
    # 任一祖先(含自己)在白名单即允许
    for ancestor in [rel, *rel.parents]:
        if str(ancestor) in whitelist:
            return

    raise ToolDeniedError(
        f"写入路径 {target.name!r} 不在白名单 {sorted(whitelist)} 内"
    )
```

**保留现状**:`DEFAULT_WRITE_WHITELIST` 字面值不变,继续含 `.writer/cache` / `.writer/agents`。白名单语义由"顶层目录名"升级为"路径前缀",但**字面值风格不变** — 用户/开发者阅读 `runtime.py` 时的认知负担为零。

### 方案 B(备选):白名单改回扁平目录名

把 `.writer/cache` 拆成 `.writer` + `cache` 两条,`_check_whitelist` 实现不变。

```python
DEFAULT_WRITE_WHITELIST = frozenset(
    {"manuscript", "outline", "characters", "world", "notes", "创意",
     ".writer", "cache"}   # 含义混乱:cache 不是顶层目录
)
```

**否决理由**:语义模糊 — `cache` 作为顶层目录允许是错的(用户能写 `cache/foo.md`)。需新增规则:`cache` 仅在与 `.writer` 合并路径时有效,等价于把语义搞复杂。

### 方案 C(备选):改 `_check_whitelist` 用 `parts[:N]` 拼接

```python
key = "/".join(rel.parts[:2])  # 检查 .writer/cache 这种 2 段路径
if key in whitelist:
    return
```

**否决理由**:硬编码前缀深度(`[:2]`),无法扩展到任意深度路径(如 `manuscript/novel1/chapter.md` —— 顶层 `manuscript` 已允许,但 `parts[:2]` = `manuscript/novel1` 反而不在白名单)。方案 A 是唯一能正确处理任意深度路径前缀的实现。

## 5. 验证步骤(Manual Reproduction)

```bash
# 1. 启动项目
printf "/init 一个穿越到唐朝的程序员 --genre 其他\n/help\n" | uv run writer
cd /tmp/test-bug04
mkdir -p .writer/cache

# 2. 通过 Python 直接调用 SafeWriteFile 触发(避免 REPL 噪声)
uv run python - <<'PY'
from pathlib import Path
from writer.tools import ToolRuntime, built_tool_registry

runtime = ToolRuntime(project_root=Path("/tmp/test-bug04"))
tool = built_tool_registry().get("safe_write_file")
result = tool.run(runtime, path=".writer/cache/test.md", content="hi", mode="create")
print(result.output)
PY

# 期望(buggy 当前):
#   ToolDeniedError: 写入路径 'test.md' 不在白名单 [..., '.writer/cache', ...] 内

# 期望(修复后):
#   已写入 /tmp/test-bug04/.writer/cache/test.md (2 字节, mode=create)
```

e2e 路径(LLM 工具循环触发):
```bash
# 配 API key 后让 LLM 工具循环尝试写缓存
printf "把当前讨论缓存到 .writer/cache/discussion.md\n" | uv run writer
# 期望(buggy): ToolDeniedError 出现在 REPL + Done(aborted)
# 期望(修复后): 写入成功 + Done(tool_loop_completed 或 answered)
```

## 6. 回归测试用例清单

| 测试文件 | 测试名 | 关键断言 | 类型 |
|---|---|---|---|
| `tests/test_tools.py` | `test_whitelist_matches_subpath` | `safe_write_file(runtime, path=".writer/cache/foo.md", ...)` 成功,无 `ToolDeniedError` | NEW |
| `tests/test_tools.py` | `test_whitelist_matches_deep_subpath` | `safe_write_file(runtime, path="manuscript/novel1/chapter.md", ...)` 成功(`manuscript` 祖先在白名单) | NEW |
| `tests/test_tools.py` | `test_whitelist_matches_agents_subpath` | `safe_write_file(runtime, path=".writer/agents/历史.md", ...)` 成功 | NEW |
| `tests/test_tools.py` | `test_whitelist_rejects_unrelated_subpath` | `safe_write_file(runtime, path="secrets/api_key", ...)` 仍被拒绝(`secrets` 不在白名单) | NEW |
| `tests/test_tools.py` | `test_whitelist_rejects_root_only` | `safe_write_file(runtime, path="AGENT.md", ...)` 走 `_guard_agent_md` 路径,白名单检查**不**触发(或早返) | NEW |
| `tests/test_tools.py` | `test_safe_write_file_rejects_outside_whitelist` | 现有 `secrets/api_key` 案例保持拒绝 | MODIFY(改断言细节:检查 `ToolDeniedError.message` 含"白名单"列表) |
| `tests/test_runtime.py` | `test_default_whitelist_includes_dot_writer_cache` | 断言 `".writer/cache" in DEFAULT_WRITE_WHITELIST` 与 `".writer/agents" in DEFAULT_WRITE_WHITELIST` | NEW |
| e2e | `tests/e2e/test_repl_dot_writer_cache.py` | REPL 启动后用 stdin 触发 LLM 工具循环写 `.writer/cache/x.md`,assert 文件存在 + Done 终结 | NEW e2e |

## 7. 风险与遗留(Risks & Follow-ups)

### 修复后仍未解决的相邻问题

- **`safe_read_file` 仍无白名单**:读取全开放,这是设计预期(LLM 需要读 LLM scratchpad)。不在本 bug 修复范围。
- **`.writer/` 顶层目录的非 cache/agents 写入仍被拒绝**(纯 `.writer/foo.md`):预期行为,但需在 `备忘 13` 加一行注释说明。
- **whitelist 字面值风格混乱**:`.writer/cache` 与 `manuscript` 在同一个集合里,一个是路径前缀、一个是顶层目录名。可读性有损但向后兼容,暂不统一。

### 与 OpenSpec 的关系

- **未来 change 提案建议名**:`fix-whitelist-path-prefix`
- **不需 spec delta**:`writer-tools` spec 里 `MAX_FILE_SIZE` / `safe_path` 行为不变,白名单语义升级属于实现细节(spec 只约束"拒绝越界"原则)。
- **文档同步**:
  - `docs/技术架构总览.md:278` — 当前说"写入类额外走白名单",改为"白名单匹配祖先路径前缀"
  - `备忘 13-核心Tool设计.md:54-95` — 补充"路径前缀语义"段
  - `openspec/specs/writer-tools/spec.md:36` — 改 `#### Scenario: Write to whitelisted subdirectory` 的 `Then` 描述

### 关联 bug

- 与 [Bug 1](./01-tool-loop-not-rebound.md) 间接相关:LLM 工具循环指向旧根目录时,即便 Bug 4 修了,`.writer/cache` 仍可能写到旧路径。修 Bug 1 后两者协同生效。