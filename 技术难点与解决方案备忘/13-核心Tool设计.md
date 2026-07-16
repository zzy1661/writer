# 核心 Tool 设计

> **2026-07-08 重要修订**:本文档原列出的 Tool 清单(`read_file` / `write_file` / `chapter_register` / `rag_query` 等 19 个)是**早期设想**。当前实装的 builtin Tool 只有 6 个,LLM 通过 `project_search` + `safe_read_file` + `safe_write_file` 自由组合完成"读、改、查、统计"工作,业务 Tool(`chapter_register` / `foreshadow_update` / `consistency_check` 等)已被 [OpenSpec `chg-markdown-skills`](../../openspec/changes/archive/2026-07-09-chg-project-skills/) 的 **Markdown SKILL.md directives** 替代。
>
> 下文先列出当前 9 个 builtin Tool,再保留跨边界实现要点(签名约束 / PEP-563 / `ToolRuntime` / `ToolRegistry` 注册名唯一 / LangChain 桥接)。

## 业务背景

Agent 需要读项目文件、查关键词、定位章节、登记伏笔、统计字数。这些能力属于"路径工具"(必须有 `project_root` 边界)和"非路径工具"(ledger / 统计),后者需要单独标注。

## 技术难点

Tool 必须表达业务语义,但又不能太多:

- 每个 Tool 增加 LLM 选择成本(同时进 LC `args_schema`,LLM 必须在 prompt 里识别)
- 业务级 Tool(`chapter_register`)如果写成 Python 类,跨项目定制就麻烦(项目级覆盖需要 hook 进类加载,不可行)
- LLM 直接编辑 Markdown 不可控(格式破坏、状态不一致)

最终决定:**路径工具 + 纯检索类工具 + 统计工具** 9 个保持 Python 类;**业务级"做什么"** 用 SKILL.md directives(让项目目录里放个 `.md` 就能覆盖)。

## 当前 builtin Tool 清单(2026-07-09 实测)

`src/writer/tools/builtin/__init__.py::built_tool_registry()` 注册 **9 个 Tool**。`safe_write_file` / `safe_edit_file` / `safe_glob` 三个由 [chg-add-write-edit-glob](2026-07-09) 补入,补齐了 2 个 shipped directive(`/大纲` `/目录`)描述的 LLM 工具流。

### 文件 / 路径类(必须有 project_root,走 `safe_path` 或路径白名单)

| Tool name | kwargs | 用途 |
| --- | --- | --- |
| `safe_read_file` | `path: str` | 读 UTF-8 文本;路径越界拒绝;`runtime.max_file_size` 截断并设 `truncated=True` |
| `safe_list_dir` | `path: str = "."` | 列目录(`d`/`f` 前缀);跳过隐藏文件;非目录抛 `ToolNotADirectoryError` |
| **`safe_write_file`** | `path`, `content`, `mode="create"\|"overwrite"\|"append"`, `backup=True` | 在白名单内写 UTF-8 文件;`mode=create` 默认拒覆盖;`mode=overwrite` 原子替换 + 备份到 `.writer/backups/<relpath>.<ISO-ts>`;`mode=append` 尾部追加(非原子、不备份);AGENT.md 仅允许 `overwrite` 并自动保留 `题材:` 行;`max_file_size` 字节限制 |
| **`safe_edit_file`** | `path`, `old_string`, `new_string`, `replace_all=False`, `dry_run=False`, `backup=True` | 精确字符串替换(Claude Code Edit 语义);`old_string` 必须唯一除非 `replace_all=True`;`dry_run=True` 只返回 unified diff 不写盘;AGENT.md 走同 3-stage guard |
| **`safe_glob`** | `pattern`, `sort_by="name"\|"mtime"` | `pathlib` 模式匹配;`sort_by="mtime"` 按修改时间排序便于查找最近编辑的文件;跳隐藏文件 |

### 检索类(路径工具 + 启发式匹配)

| Tool name | kwargs | 用途 |
| --- | --- | --- |
| `project_search` | `query: str`, `path: str = "."`, `limit: int = 20` | 项目目录内行级子串匹配(grep 模拟);`.md`/`.txt` 后缀;非 UTF-8 跳过;IO 错误转 `ToolResult` 不外溢 |

### 业务领域类(ledger / locator)

| Tool name | kwargs | 用途 |
| --- | --- | --- |
| `foreshadow_search` | `id / tags / status / chapter_range / keyword`(kw-only) | 查询 `<project_root>/伏笔.yaml`;5 条件 AND;S0 走 sentinel 识别返回友好提示 |
| `chapter_locate` | `chapter: str \| None = None` | 把 `"1.3"` / `"卷一第三章"` / 标题解析为标准句柄;**S0 stub**,仅 echo 输入 |

### 统计类

| Tool name | kwargs | 用途 |
| --- | --- | --- |
| `wordcount` | `text: str \| None = None`, `path: str \| None = None` | 估算文本 / 项目文件的粗略字数(剔除空白);中文友好 |

### 写入白名单(`runtime.allowed_write_paths`,per chg-add-write-edit-glob)

`safe_write_file` 与 `safe_edit_file` 在 `_check_whitelist()` 阶段要求目标路径的第一段目录在白名单内:

```python
DEFAULT_WRITE_WHITELIST: frozenset[str] = frozenset({
    "manuscript", "outline", "characters", "world", "notes", "创意",
    "史实", "伏笔", "人设",   # 题材子目录
    ".writer",                 # metadata(不含 AGENT.md 顶部)
})
```

`AGENT.md` 是例外:不走白名单(`first=""`),走 `_guard_agent_md()` 3 段保护:

1. `mode` 必须 `overwrite`(不能 create / append,会破坏元信息结构)
2. `content` 必须包含 `## 当前状态` 段
3. 现有 `题材:` 行被新内容漏掉时自动保留(防止 `Engine.refresh_project_genre` 失效)

`max_file_size` 默认 50_000 字节;超出抛 `ToolOutputTooLargeError`(上抛,engine `except ToolError` 兜底)。

### 路由触发说明

- `/字数统计` → `wordcount(path=...)`(`RuleBasedIntentRouter`)
- 自然语言含"伏笔"或 `F\d+` 模式 → `foreshadow_search(id=..., keyword=...)`(`_parse_foreshadow_args`)
- SKILL.md directive(`/大纲` `/目录`)→ `_run_directive` 把 body + references 喂给 LLM 工具循环,LLM 自由组合 9 个 Tool
- LLM 工具循环里的自由调用 → 9 个 Tool 任意组合,LLM 决定

### 已**移除**的旧 Tool(常见误以为存在的)

| 旧 Tool | 替代 |
| --- | --- |
| `foreshadow_query(query)` | `foreshadow_search(id / tags / status / chapter_range / keyword)`(语义从"模糊查"变"结构化查") |
| `rag_query` / `persona_search` / `build_context_pack` | 删除 RAG,改用 `project_search` + `_build_canon_block` 文件拼装 |
| `chapter_register` / `append_revision_record` / `parse_outline` / `parse_toc` | LLM 用 `safe_read_file` + `safe_write_file` + `safe_edit_file` + `safe_glob` 直接操作 Markdown(由 SKILL.md directive 教 LLM 怎么做) |
| `read_agent_state` / `update_agent_state` | LLM 用 `safe_read_file("AGENT.md")` 直接读;改用 `safe_edit_file` 走 AGENT.md 3-stage guard |
| `ask_user_choice` / `ask_user_text` / `confirm_action` | engine 发 `Interrupt` 事件,REPL 渲染;Tool 层不负责 |

## Tool 设计原则

- LLM 调用 builtin Tool,**不直接**编辑正典(由 directive 引导规则)
- 路径 Tool 必须 `runtime.safe_path()` 防越界
- 写入 Tool 还必须走 `runtime.allowed_write_paths` 白名单(`AGENT.md` 走 3-stage guard 例外)
- 写入采用 tmp + `os.replace` 原子替换;破坏性写默认备份到 `.writer/backups/<relpath>.<ISO-ts>`(可显式 `backup=False` 关闭)
- IO 错误(`PermissionError` / `OSError` / `UnicodeDecodeError`)转 `ToolResult(metadata.error=...)`,**不**外溢到 engine 的 `except Exception`
- 写入 Tool 返回结构化结果,便于 REPL 渲染 `tool_calls_made` 等统计

---

## 跨边界实现要点(落地 Bridge 时的坑)

把上面的 `Tool` 接到 LangChain `StructuredTool` 时,有几个写备忘 13 时没遇到、但落地后必须记录的点:

### 1. Tool 签名必须是命名 keyword,不能用 `**kwargs`

`writer.tools` 已经踩过这个坑:

```python
# ❌ 失败: LangChain StructuredTool 会把整个 input 当成单字段
def run(self, runtime: "ToolRuntime", **kwargs: Any) -> ToolResult:
    path = kwargs.get("path")

# ✅ 正确: 显式命名参数,让 introspect 能识别每个字段
def run(self, runtime: "ToolRuntime", *, path: str) -> ToolResult:
    target = runtime.safe_path(path)
```

原因: `StructuredTool.from_function()` 用 `inspect.signature()` 推导 `args_schema`; 遇到 `**kwargs` 时它认为"这是一个 dict 参数",而不是"展开字段",导致 `tool.invoke({"path": "x"})` 被解析成一个 dict 字段而不是 `{path: "x"}`。

### 2. PEP-563 注解需要 `typing.get_type_hints` 解回真实类型

`from __future__ import annotations` 把所有注解变成字符串。`inspect.signature` 看到的是 `path: "'str'"` 而不是 `path: str`,直接拿去 `pydantic.create_model` 会失败。

```python
import inspect
from typing import get_type_hints

sig = inspect.signature(tool.run)
resolved = get_type_hints(tool.run)  # 把字符串注解解回类型对象

fields = {}
for name, param in sig.parameters.items():
    if name in {"self", "runtime"}:
        continue
    fields[name] = (resolved.get(name, Any), Field(default=...))
ArgsModel = create_model(f"{tool.name}_args", **fields)
```

### 3. `ToolRuntime` 必须按参数注入,不能 module-level 全局

`writer/tools/runtime.py` 的当前形态:

```python
class ToolRuntime:
    def __init__(self, project_root: Path, *, shell_enabled: bool = False,
                 max_file_size: int = 50_000) -> None:
        self.project_root = project_root.resolve()  # resolve 一次,后续 safe_path 比较用 canonical 形式
        self.shell_enabled = shell_enabled
        self.max_file_size = max_file_size

    def safe_path(self, raw: str | Path) -> Path:
        candidate = (self.project_root / raw).resolve()
        if self.project_root not in (candidate, *candidate.parents):
            raise ToolDeniedError(f"路径越界: {candidate}")
        return candidate
```

每个 session 构造一个 `ToolRuntime`,Tools 通过 `run(runtime, **kwargs)` 接收。Module-level 全局会切断多 session、多 project 的能力,而且测试时要 monkey-patch 很麻烦。

`Engine.set_project_root()` 触发 `ToolRuntime` 热替换(per 备忘 16 的 M6 修复),旧的 duck-typed mutation 已删除。

### 4. `ToolRegistry` 注册名必须唯一,重复注册立即报错

```python
def register(self, tool: Tool) -> "ToolRegistry":
    if tool.name in self._tools:
        raise ValueError(f"工具重复注册: {tool.name!r}")
    self._tools[tool.name] = tool
    return self
```

重复名启动时拒绝,不要等到第一次 `invoke()` 才返回 `ToolNotFoundError`,那样定位成本高。

### 5. Tool 包装为 LangChain `BaseTool` 的标准做法

`writer/tools/langchain_bridge.py::to_langchain_tools(registry, runtime)` 提供了现成实现。关键点:

- 现场 `inspect.signature + get_type_hints + pydantic.create_model` 构造 `args_schema`(上述 1+2)
- 每个 `BaseTool` 闭包 capture `runtime`,所以同一个 registry 可以为不同 session 产出多组 base tools
- `ToolResult.output` 透传给 LangChain;`truncated` / `metadata` 在本层丢弃,由 LangGraph state 单独记录

### 6. ToolDescriptor 提供给 LLM 的工具目录

`ToolRegistry.describe()` 2026-07-08 新增(`src/writer/tools/registry.py`),返回 `list[ToolDescriptor]`,`ReActAgent` 用它喂 LLM 的 `bind_tools` / JSON-prompt:

```python
@dataclass(frozen=True)
class ToolDescriptor:
    name: str
    description: str
    args_schema: type[BaseModel] | None
```

`args_schema` 复用 `_build_args_schema`,与 `to_langchain_tools()` 保持同步。

## 更新后的验收标准

除上面 6 条外,补充:

- Tool 的 `run()` 必须是 `(self, runtime, *, named: type, ...)` 形态,不能 `**kwargs`
- 每个 Tool 接受 `ToolRuntime` 作为显式参数,不读 module 全局
- `ToolRegistry.register()` 在名字重复时抛 `ValueError`
- `ToolRegistry.describe()` 产出的 `ToolDescriptor` 字段与 `to_langchain_tools(registry, runtime)` 一致
- IO 错误必须转 `ToolResult(metadata.error=...)`,不外溢到 engine 的 `except Exception`
- 业务级"做什么"不进 Tool 层,改用 SKILL.md directives(`src/writer/skills/_shipped/`)
- `safe_write_file` 等写入类 Tool 暂不内置(由 LLM 走 `safe_read_file` + `safe_write_file` 的纯文件层;若未来需要"事务写入"再补)