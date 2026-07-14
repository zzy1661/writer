# 06 · Tool 层与 Runtime

> 对应代码:`src/writer/tools/{protocol,registry,runtime,langchain_bridge,errors}.py` + `src/writer/tools/builtin/*.py`
> 设计备忘:[`备忘 07-工具注册与文件权限`](../../技术难点与解决方案备忘/07-工具注册与文件权限安全.md) + [`备忘 13-核心Tool设计`](../../技术难点与解决方案备忘/13-核心Tool设计.md)

---

## 6.1 设计动机

**问题**:LLM 需要读项目文件、写大纲、查伏笔——但 LLM **不能直接调文件系统**。Tool 层就是 LLM 与项目文件系统之间的「受控边界」:

1. **路径白名单**:LLM 只能写 `outline/` `manuscript/` 等允许目录
2. **签名稳定**:LangChain `StructuredTool.from_function` 用 `**kwargs` 推不出 schema,Tool 必须用命名 keyword
3. **错误转译**:IO 错误不外溢到引擎边界,统一转 `ToolResult(metadata.error="...")`
4. **可观测**:`ToolRegistry.describe()` 暴露工具目录给 LLM 决策

## 6.2 `Tool` Protocol

> 对应代码:`src/writer/tools/protocol.py`

```python
@runtime_checkable
class Tool(Protocol):
    name: str
    description: str

    def run(self, runtime: ToolRuntime, **kwargs: Any) -> ToolResult: ...
```

### 核心约束

- **无状态**:Tool 是 stateless 对象,会话级状态通过 `ToolRuntime` 注入
- **`**kwargs` 必须有名字**:`def run(self, runtime, *, path: str)`(命名 keyword),否则 LangChain `StructuredTool.from_function` 推不出 args_schema
- **`@runtime_checkable`**:`isinstance(obj, Tool)` 走 attribute presence 检查,测试 fake 必须有 `name` / `description` / `run`

### `ToolResult`

```python
@dataclass(frozen=True)
class ToolResult:
    output: str                          # 人类可读载荷
    truncated: bool = False              # runtime 是否截断了输出
    metadata: Mapping[str, Any] = {}     # 结构化辅助信息
```

`metadata` 字段是关键——LLM 看到 `metadata.chapter_count=10` 之类的结构化字段比解析字符串好得多。

## 6.3 `ToolRuntime` — 会话级守卫

> 对应代码:`src/writer/tools/runtime.py`

```python
@dataclass
class ToolRuntime:
    project_root: Path                          # 所有路径都需在此之下
    allowed_write_paths: set[Path] | None = None  # 写白名单(None = 默认)
    max_file_size: int = 256 * 1024             # 默认 256KB
    backup_dir: Path | None = None              # .writer/backups/<relpath>.<ISO-timestamp>

    def safe_path(self, user_path: str | Path, *, must_exist: bool = True) -> Path:
        """把 user_path 解析为绝对路径,校验在 project_root 之内。"""

    def safe_write_path(self, user_path: str | Path) -> Path:
        """校验 user_path 在 allowed_write_paths 白名单内。"""
```

### `safe_path` 关键算法

```python
def safe_path(self, user_path: str | Path, *, must_exist: bool = True) -> Path:
    candidate = (self.project_root / user_path).resolve()
    try:
        candidate.relative_to(self.project_root)
    except ValueError:
        raise ToolPermissionError(f"路径越界: {candidate} 不在 {self.project_root} 之内")
    if must_exist and not candidate.exists():
        raise ToolNotFoundError(f"文件不存在: {candidate}")
    return candidate
```

**关键陷阱**:`relative_to` 用 try/except,不是 `if`.`startswith()`——后者会被 `/project_root_evil/` 欺骗。

### 默认白名单 `DEFAULT_WRITE_WHITELIST`

```python
DEFAULT_WRITE_WHITELIST: frozenset[Path] = frozenset([
    "manuscript", "outline", "characters", "world", "notes",
    "创意", ".writer/cache", ".writer/agents",
])
```

8 个目录,覆盖「写正文、写大纲、写人物、世界观、笔记、创意、writer 缓存、自定义 agent」。`AGENT.md` 通过 guard 显式旁路。

## 6.4 `ToolRegistry` — 注册表

> 对应代码:`src/writer/tools/registry.py`

```python
class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, Tool] = {}
        self._descriptors: dict[str, ToolDescriptor] = {}

    def register(self, tool: Tool) -> None:
        """注册一个 Tool,名字重复立即抛 ValueError。"""
        if tool.name in self._tools:
            raise ValueError(f"工具 {tool.name!r} 已注册")
        self._tools[tool.name] = tool
        self._descriptors[tool.name] = ToolDescriptor(name=tool.name, description=tool.description, ...)

    def invoke(self, name: str, runtime: ToolRuntime, **kwargs) -> ToolResult:
        """查找 Tool 并执行;未找到抛 ToolNotFoundError。"""
        tool = self._tools.get(name)
        if tool is None:
            raise ToolNotFoundError(f"未知工具 {name!r}; available: {sorted(self._tools)}")
        return tool.run(runtime, **kwargs)

    def describe(self) -> list[ToolDescriptor]:
        """暴露给 LLM 的工具目录。ReActAgent 用它构造 system prompt。"""
        return list(self._descriptors.values())
```

### `built_tool_registry()` — 默认装配

```python
def built_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(SafeReadFile())
    registry.register(SafeListDir())
    registry.register(SafeWriteFile())
    registry.register(SafeEditFile())
    registry.register(SafeGlob())
    registry.register(ProjectSearch())
    registry.register(ForeshadowSearch())
    registry.register(ChapterLocate())  # S0 stub
    registry.register(Wordcount())
    return registry
```

**注册顺序不重要**(字典查找),但 describe 顺序 = 注册顺序 = LLM 看到的顺序。

## 6.5 9 个 builtin Tool 详解

| name | kwargs | 用途 | 源码 |
| ---- | ------ | ---- | ---- |
| `safe_read_file` | `path` | 读文件;`max_file_size` 截断 | `file_tools.py::SafeReadFile` |
| `safe_list_dir` | `path="."` | 列目录;跳隐藏;非目录抛 `ToolNotADirectoryError` | `file_tools.py` |
| **`safe_write_file`** | `path`, `content`, `mode="create"`, `backup=True` | 3 种 mode(create 拒覆盖 / overwrite 原子写+备份 / append 追加);AGENT.md 走 3-stage guard | `file_tools.py::SafeWriteFile` |
| **`safe_edit_file`** | `path`, `old_string`, `new_string`, `replace_all=False`, `dry_run=False`, `backup=True` | Claude Code Edit 语义;`old_string` 不唯一 + 未传 `replace_all` 拒绝;`dry_run` 返回 unified diff | `file_tools.py::SafeEditFile` |
| **`safe_glob`** | `pattern`, `sort_by="name"` | `pathlib` 模式匹配;`sort_by="mtime"` 最新优先 | `glob_tools.py` |
| `project_search` | `query`, `path="."`, `limit=20` | 行级子串匹配;`.md`/`.txt` 后缀;IO 错误转 `ToolResult` | `analysis_tools.py` |
| `foreshadow_search` | `id`/`tags`/`status`/`chapter_range`/`keyword`(5 kw-only) | 查 `<project_root>/伏笔.yaml`;多条件 AND | `foreshadow_tools.py` |
| `chapter_locate` | `chapter=None` | S0 stub,echo 输入 | `locate_tools.py` |
| `wordcount` | `text=None`, `path=None` | 中文友好字数统计 | `analysis_tools.py` |

### 关键示例:`SafeWriteFile` 的 3-stage guard

写入 `AGENT.md` 必须满足三道关卡(per `chg-add-write-edit-glob`):

```python
def run(self, runtime, *, path: str, content: str, mode: str = "create", backup: bool = True) -> ToolResult:
    target = runtime.safe_write_path(path)

    if target.name == "AGENT.md":
        # Stage 1:必须 overwrite mode
        if mode != "overwrite":
            return ToolResult(output="", metadata={"error": "AGENT.md 必须用 mode=overwrite"})
        # Stage 2:内容必须含 ## 当前状态
        if "## 当前状态" not in content:
            return ToolResult(output="", metadata={"error": "AGENT.md 内容必须含 ## 当前状态 段"})
        # Stage 3:旧题材行自动 merge(避免 race)
        old_content = target.read_text(encoding="utf-8")
        new_content = _merge_genre_line(old_content, content)
        # 写文件...
```

**为什么这样设计**:LLM 经常改写整个 AGENT.md 但忘了保留某些字段;merge 避免「题材: 历史」被「题材: 言情」意外覆盖。

### 关键示例:`SafeEditFile` 的 `dry_run`

```python
def run(self, runtime, *, path, old_string, new_string, replace_all=False, dry_run=False, backup=True):
    target = runtime.safe_path(path, must_exist=True)
    content = target.read_text(encoding="utf-8")
    count = content.count(old_string)
    if count == 0:
        return ToolResult(output="", metadata={"error": f"未找到 old_string in {path}"})
    if count > 1 and not replace_all:
        return ToolResult(output="", metadata={"error": f"old_string 在 {path} 出现 {count} 次,需 replace_all=True"})
    new_content = content.replace(old_string, new_string, -1 if replace_all else 1)
    if dry_run:
        diff = "\n".join(unified_diff(content.splitlines(), new_content.splitlines(), lineterm=""))
        return ToolResult(output=diff, metadata={"dry_run": True, "diff_lines": len(diff.splitlines())})
    # 实际写...
```

**`dry_run` 让 LLM 先预览 diff**,再决定是否真正写入;避免一次错误改写需要回滚。

## 6.6 `foreshadow_search` — 5 kw-only 参数 AND 语义

```python
class ForeshadowSearch(Tool):
    name = "foreshadow_search"
    description = "在 <project_root>/伏笔.yaml 中按 id/tags/status/chapter_range/keyword 查询;多条件 AND"

    def run(
        self, runtime,
        *,
        id: str | None = None,
        tags: list[str] | None = None,
        status: str | None = None,
        chapter_range: tuple[int, int] | None = None,
        keyword: str | None = None,
    ) -> ToolResult:
        # S0 路径下 project_root 是哨兵 → 返回 metadata.error="no_project_root"
        if str(runtime.project_root) == "/__no_project__":
            return ToolResult(output="", metadata={"error": "no_project_root"})

        ledger_path = runtime.project_root / "伏笔.yaml"
        if not ledger_path.exists():
            return ToolResult(output="", metadata={"hits": 0, "message": "伏笔.yaml 不存在"})

        entries = load_ledger(ledger_path)
        hits = filter_entries(entries, id=id, tags=tags, status=status, chapter_range=chapter_range, keyword=keyword)
        return ToolResult(
            output=format_hits(hits),
            metadata={"hits": len(hits), "total_entries": len(entries)},
        )
```

**5 个参数都是 kw-only**,LLM 必须显式命名调用;多条件之间是 **AND** 语义。

## 6.7 路径安全深度约束

### `safe_path` 必做 3 件事

1. **解析为绝对路径**:`(project_root / user_path).resolve()`,处理 `..` 和软链接
2. **`relative_to` 校验**:`try: candidate.relative_to(project_root) except ValueError: raise`
3. **存在性检查**:默认 `must_exist=True`,读操作强制要求文件存在

### `safe_write_path` 额外白名单

```python
def safe_write_path(self, user_path):
    target = self.safe_path(user_path, must_exist=False)
    if self.allowed_write_paths is None:
        allowed = DEFAULT_WRITE_WHITELIST
    else:
        allowed = self.allowed_write_paths

    # Ancestor prefix match:target 必须在某个 allowed 子目录下
    for prefix in allowed:
        try:
            target.relative_to(prefix)
            return target
        except ValueError:
            continue
    raise ToolPermissionError(f"路径 {target} 不在写入白名单内;allowed: {allowed}")
```

**Bug 04 修复**:祖先路径前缀匹配,避免 `/project_root/manuscript_evil/` 欺骗白名单(`/project_root/manuscript` 是白名单)。

## 6.8 IO 错误处理约定

```python
def safe_read_file_impl(runtime, *, path):
    try:
        target = runtime.safe_path(path, must_exist=True)
        content = target.read_text(encoding="utf-8")
    except FileNotFoundError:
        return ToolResult(output="", metadata={"error": "not_found"})
    except PermissionError:
        return ToolResult(output="", metadata={"error": "permission_denied"})
    except UnicodeDecodeError:
        return ToolResult(output="", metadata={"error": "not_utf8"})
    except ToolError:
        raise  # safe_path 已经抛 ToolError,让它继续传播到 engine 边界
    # 没有 `except Exception` 兜底 —— 未知错误让 engine except Exception 处理
    if len(content.encode("utf-8")) > runtime.max_file_size:
        return ToolResult(output=content[:runtime.max_file_size], truncated=True, metadata={"truncated_at": runtime.max_file_size})
    return ToolResult(output=content)
```

**核心约定**:**已知 IO 错误转 `ToolResult(metadata.error=...)`**,**未知异常外溢到 engine `except Exception`**。这条约定让 REPL turn 不会被单条 Tool 调用失败打断。

## 6.9 `langchain_bridge` — Tool → LangChain 工具包装

> 对应代码:`src/writer/tools/langchain_bridge.py`

ReActAgent 需要把 Tool 暴露给 LangChain(`bind_tools(tools)`)。包装:

```python
def to_langchain_tools(registry: ToolRegistry, runtime: ToolRuntime) -> list[BaseTool]:
    """把 registry 里的所有 Tool 包装为 LangChain StructuredTool。"""
    def _make_lc_tool(tool: Tool) -> BaseTool:
        # 用 inspect 提取 run 的命名 kw-only 参数
        sig = inspect.signature(tool.run)
        params = {
            name: inspect.Parameter(name, inspect.Parameter.KEYWORD_ONLY, annotation=p.annotation)
            for name, p in sig.parameters.items()
            if name != "self" and name != "runtime"
        }
        # 用 Pydantic create_model 动态构造 args_schema
        schema = create_model(f"{tool.name}Args", **params)
        return StructuredTool(
            name=tool.name,
            description=tool.description,
            args_schema=schema,
            func=lambda **kwargs: tool.run(runtime, **kwargs),
        )
    return [_make_lc_tool(t) for t in registry._tools.values()]
```

**关键**:`StructuredTool.from_function` 用 `**kwargs` 函数会丢字段,所以我们**手动构造** `args_schema` 用 `pydantic.create_model`。

## 6.10 完整数据流:LLM 调用 `safe_write_file`

```
LLM 读 directive body + agent identity
   ↓
LLM 思考:我需要先了解项目状态,然后写大纲
   ↓
LLM 产出 AgentAction(call_tool, tool_name="safe_write_file", arguments={"path": "outline/大纲.md", "content": "..."})
   ↓
ReActAgent 调用 registry.invoke("safe_write_file", runtime, path="outline/大纲.md", content="...")
   ↓
SafeWriteFile.run(runtime, path="outline/大纲.md", content="...", mode="create"):
    target = runtime.safe_write_path("outline/大纲.md")
    # 校验:outline/ 在 DEFAULT_WRITE_WHITELIST → 通过
    # mode="create" 且文件已存在 → 抛 ToolPermissionError 或转 ToolResult
    # ...
    return ToolResult(output="已写入 outline/大纲.md", metadata={"bytes": 1234})
   ↓
ReActAgent yield ToolResult(output="已写入 outline/大纲.md")
   ↓
Engine 继续 ReAct 循环 → LLM 看到 ToolResult → 产出 answer_directly
```

---

## 6.11 进一步阅读

- [09-LLM工具循环](09-LLM工具循环.md) —— Tool 怎么被 LangChain 消费
- [备忘 07-工具注册与文件权限](../../技术难点与解决方案备忘/07-工具注册与文件权限安全.md)
- [备忘 13-核心Tool设计](../../技术难点与解决方案备忘/13-核心Tool设计.md)