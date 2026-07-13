# 检索实现方案(foreshadow ledger + project grep)

> **2026-07-08 重要修订**:本文档原标题《RAG 与检索实现方案》描述基于 FAISS + 中文嵌入的向量检索方案。该方案已经在 [OpenSpec `chg-remove-rag`](../../openspec/changes/archive/2026-07-08-chg-remove-rag/) 落地过程中**整体删除**(`src/writer/rag.py` 整文件、`pyproject.toml` 的 `faiss-cpu>=1.8.0` 依赖、`ProjectRagIndex` / `HashEmbeddings` / `RagHit` / `collect_project_documents` / `format_hits` 全删)。
>
> 本文以**新形态**重写。删除原因与最终方案见后文。

## 问题

`/大纲`、`/目录`、`/创作`、`/审核` 等命令必须自动取到当前任务所需资料,包括大纲、目录、人物、世界观、伏笔、史实和前文摘要。检索层如何实现?

## 旧方案(已删除)

> 已删除,不再代表项目实现,仅作历史留档。

- 结构化定位(章节 ID → `目录/目录.md` 段落)
- 关键词检索(BM25 + `jieba` 中文分词)
- 向量检索(FAISS-CPU + `BAAI/bge-large-zh-v1.5` 中文嵌入)
- 动态补充(命中硬规则时强制 `topup`)
- Token 裁剪(`prep_context` 按角色预算裁剪)

### 旧实现脚手架(已删除)

```python
from langchain_community.vectorstores import FAISS
from langchain_core.documents import Document
from langchain_openai import OpenAIEmbeddings
from langchain_text_splitters import MarkdownHeaderTextSplitter


def build_canon_index(project_root: Path) -> FAISS:
    outline = (project_root / "大纲" / "大纲.md").read_text(encoding="utf-8")
    splitter = MarkdownHeaderTextSplitter(
        headers_to_split_on=[("#", "h1"), ("##", "h2"), ("###", "h3")]
    )
    docs = splitter.split_text(outline)
    embeddings = OpenAIEmbeddings(model="text-embedding-3-large", ...)
    return FAISS.from_documents(docs, embeddings)
```

---

## 当前方案(2026-07-08 起)

### 设计

放弃向量检索,改为**结构化 ledger + 文件 grep** 双轨:

1. **伏笔召回**:走 `<project_root>/伏笔.yaml` 结构化 ledger + 多条件 AND 过滤(`foreshadow_search` tool)
2. **关键词召回**:走项目目录 grep(`project_search` tool,行级子串匹配)
3. **正典上下文**:走纯文件拼装(`engine/context.py::_build_canon_block`,见 [备忘 03](./03-长篇上下文管理与RAG检索.md))

### 1. 伏笔 ledger(`ForeshadowSearch`)

`src/writer/tools/builtin/foreshadow_tools.py` + `src/writer/tools/builtin/foreshadow_ledger.py`:

- 路径无关:工具自动定位 `<runtime.project_root>/伏笔.yaml`
- S0 路径:sentinel `"/__no_project__"` 识别后返回友好提示(`metadata.error="no_project_root"`),不读盘
- Schema 错误:`ForeshadowLedgerSchemaError` → `metadata.error="schema"`,不外溢到 engine 边界

入口参数(5 个 kw-only):

| 参数 | 类型 | 用途 |
| --- | --- | --- |
| `id` | `str \| None` | 例如 `F003` 精确匹配 |
| `tags` | `list[str] \| None` | 全部命中(AND) |
| `status` | `Literal["laid", "paid", "all"]` | 过滤埋设/回收状态,默认 `all` |
| `chapter_range` | `tuple[int, int] \| None` | `[laid_chapter, paid_chapter]` 区间 |
| `keyword` | `str \| None` | 子串模糊匹配(`notes` / `title`) |

多条件组合用 AND,所有路径走 `query_ledger()`(`foreshadow_ledger.py`),无网络依赖。

### 2. 项目 grep(`ProjectSearch`)

`src/writer/tools/builtin/analysis_tools.py`:

```python
class ProjectSearch:
    name = "project_search"
    description = "在项目目录内搜索关键词;返回匹配文件、行号和片段。"

    def run(self, runtime, *, query, path=".", limit=20) -> ToolResult:
        # 行级子串匹配,无嵌入、无 RAG 兜底
```

实现要点:

- `_iter_text_files()` 递归扫 `.md` / `.txt`,跳过 `.` 开头目录
- `target.is_file()` 走单文件模式,`is_dir()` 走目录模式
- `limit` 触发提前返回并设 `truncated=True`
- `UnicodeDecodeError` 跳过(非 UTF-8 文件不打扰 LLM)
- `PermissionError` / `OSError` 走 `ToolResult(metadata.error="io")`,不外溢到 engine 的 `except Exception`

### 3. 上下文拼装(`_build_canon_block`)

`src/writer/engine/context.py` 把"按章节 ID 召回正典"换成"4 层文件拼装":

| 层 | 文件 | 何时启用 |
| --- | --- | --- |
| outline | `outline/大纲.md` 全文 | 文件存在 |
| characters | `characters/*.md` 全文 | 目录存在 |
| chapter_summaries | `chapter_summaries.json` 切片 | 文件存在 |
| 最近一章 | `manuscript/<latest>.md` | `manuscript/` 非空 |

预算裁剪由 LLM 工具循环的 caller 负责(目前是 `ReActAgent` 把 `ContextPack` 喂给 LLM 之前的预处理)。

---

## 核心依赖版最小代码

```python
# 文件拼装版(_build_canon_block)
from pathlib import Path


def build_canon_block(project_root: Path) -> str:
    parts: list[str] = []
    outline = project_root / "outline" / "大纲.md"
    if outline.is_file():
        parts.append(f"## 大纲\n\n{outline.read_text(encoding='utf-8')}")
    characters = project_root / "characters"
    if characters.is_dir():
        char_text = "\n\n".join(
            p.read_text(encoding="utf-8")
            for p in sorted(characters.glob("*.md"))
        )
        if char_text:
            parts.append(f"## 人物\n\n{char_text}")
    return "\n\n---\n\n".join(parts)
```

```python
# 伏笔 ledger 查询
from writer.tools.builtin.foreshadow_tools import ForeshadowSearch
from writer.tools.runtime import ToolRuntime


def search_foreshadow(root: Path, query: str) -> str:
    tool = ForeshadowSearch()
    runtime = ToolRuntime(project_root=root)
    result = tool.run(runtime, keyword=query)
    return result.output
```

```python
# 项目 grep
from writer.tools.builtin.analysis_tools import ProjectSearch


def grep_project(root: Path, query: str) -> str:
    tool = ProjectSearch()
    runtime = ToolRuntime(project_root=root)
    result = tool.run(runtime, query=query, path=".", limit=20)
    return result.output
```

## 落地建议

- **不要再引入 FAISS / BM25 / 中文嵌入**。`faiss-cpu` 依赖已经从 `pyproject.toml` 删除;`langchain-community` 保留(LLM tool bridge 仍用)
- 章节定稿后写 `chapter_summaries.json` 的路径走 `safe_write_file`(LLM 工具调用),不要 backport 旧 RAG 的 `collect_project_documents`
- 伏笔 ledger 的写入路径(创建 / 更新 / 回收)走 LLM 工具调用或未来 LLM 化 `init_brief`
- 关键字 / 子串模糊搜索靠 `project_search`,不要在应用层叠 BM25

## 验收标准

- `伏笔.yaml` 写错字段名 → `foreshadow_search` 返回 `metadata.error="schema"`,不中断 REPL
- 章节定稿后 `chapter_summaries.json` 应能被下次 `_build_canon_block` 自动读到
- 任意路径(`../`)在 `project_search` 必须被 `safe_path` 拒绝
- `foreshadow_search` 的多条件查询必须全部命中(AND),不能 OR
- S0 路径下 `foreshadow_search` / `project_search` 都不允许读盘(sentinel 识别或 safe_path 拒绝)

## 与已有文档的关系

- 与 [备忘 03](./03-长篇上下文管理与RAG检索.md) 互为补充:备忘 03 描述"上下文拼装",本文描述"检索工具"
- 与 [备忘 13](./13-核心Tool设计.md) 互为补充:备忘 13 列出 builtin Tool 清单,本文列出检索类 Tool 的具体语义
- 与 [备忘 17](./17-七种系统编排方式与本项目落地映射.md) "RAG 多查询融合"段落的关系:该段已不适用,改为"project_search + foreshadow_search 多工具组合"