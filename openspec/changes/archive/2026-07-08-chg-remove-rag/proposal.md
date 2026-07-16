## Why

`ProjectRagIndex` (`src/writer/rag.py:59`) 当前是项目唯一的"自动召回"路径，被三处调用：`context.py:133` 拼 canon block、`analysis_tools.py:ProjectSearch` L112-117 RAG 兜底、`foreshadow_tools.py:ForeshadowQuery` L23。它以 `HashEmbeddings`（同文件 L33-56，sha256+bigram 的确定性占位实现）做向量召回——对真实中文网文查询召回率接近 0；对改写后的同义表达（如"玉簪" / "那支簪子"）完全无能为力。

与此同时，项目已有 Claude Code 风格的工具集（`safe_read_file` / `safe_list_dir` / `project_search` / `chapter_locate` / `chapter_summaries.json`），并已经为 50 万字规模做了**精确匹配 + 预压缩摘要**这条更对的路。RAG 这条路径是占位骨架留下来的过工程：挂着一个永远不会真正工作的 embedder，每 query 重建 FAISS 索引（`rag.py:71`），索引目录 (`INDEX_DIRS`) 还把 `outline/` `characters/` 这种小到可以整篇 Read 的目录也卷进向量空间。

## What Changes

- **删除** `src/writer/rag.py` 整个模块（包括 `ProjectRagIndex` / `HashEmbeddings` / `RagHit` / `collect_project_documents` / `format_hits`）。**BREAKING**（公开 API 下线）
- **重写** `src/writer/context.py::_build_canon_block`：不再调 RAG，改为"整篇 outline + 整篇 characters + 该章节及前 N 章的 summary 切片 + 最近一章原文"的纯文件拼装
- **移除** `src/writer/tools/builtin/analysis_tools.py:ProjectSearch` L100-117 的 RAG 兜底分支；`project_search` 退化为纯 grep（与 Claude Code 的 Grep 行为一致）
- **重命名 + 重构** `foreshadow_query` 工具为 `foreshadow_search`，参数从 `query: str` 改为结构化 `tags: list[str]` / `status: Literal["laid","paid","all"]` / `chapter_range: tuple[int,int] | None` / `keyword: str | None`；背后走 `伏笔.yaml`（或 `.json`）的 ledger 文件而非 embedding。**BREAKING**（工具名 + 参数 shape 都变）
- **新增** `伏笔.yaml` ledger 文件结构（项目初始化时由 `writer new` 或 `/init` 创建；空 ledger 也允许存在）
- **删除** `pyproject.toml` 中的 `faiss-cpu>=1.8.0` 依赖（L28）；评估 `langchain-community` 是否还需要（FAISS 移除后大概率也不再需要）**BREAKING**（依赖减项，下游需 `uv sync`）
- **测试** `tests/test_context_rag.py` 改名为 `tests/test_context.py` 并改断言；新增 `tests/test_foreshadow_ledger.py` 覆盖新结构化查询

## Capabilities

### New Capabilities

- `foreshadow-ledger`: 项目级伏笔登记表（YAML 文件）+ 结构化查询工具 `foreshadow_search`。取代原 `ForeshadowQuery`（基于 RAG 模糊匹配）。支持按 ID / tag / status（laid/paid/all）/ chapter 范围 / 关键字子串查询。这是新的 capability，因为它引入了**新文件结构**（伏笔 ledger schema）和**新工具行为契约**。

### Modified Capabilities

- `intent-routing`: 现有 spec 引用了 `foreshadow_query` 工具及 `arguments={"query": "F003"}` 的参数 shape（L17-19、L33-35）。改名为 `foreshadow_search`、参数改为 `{tags, status, chapter_range, keyword}` 后，这两条 scenario 必须用 delta 形式更新。路由器对伏笔类查询的 routing 行为本身（仍走 `call_tool` action_type）不变。
- `engine-loop`: 现有 spec 引用了 `foreshadow_query` 作为 `call_tool` 路径的示例（L21-26、L72、L75-76）。工具名/参数 shape 变更后，scenario 中的 `foreshadow_query` / `query="F003"` 必须更新。引擎 dispatch 行为本身（仍是 `ToolCall` → `ToolResult` → `Done(tool_completed)`）不变。

## Impact

**影响文件**（5 个 src + 2 个 test + 1 个 spec 改 1 个 pyproject）：
- `src/writer/rag.py`（整文件删除）
- `src/writer/context.py`（重写 `_build_canon_block`）
- `src/writer/tools/builtin/analysis_tools.py`（`ProjectSearch` 移除 RAG 分支）
- `src/writer/tools/builtin/foreshadow_tools.py`（`ForeshadowQuery` → `ForeshadowSearch`，新增 `伏笔.yaml` 加载与解析）
- `src/writer/tools/builtin/__init__.py`（重导出新工具名）
- `pyproject.toml`（删 `faiss-cpu`，评估 `langchain-community`）
- `tests/test_context_rag.py` → `tests/test_context.py`（断言重写）
- `tests/test_foreshadow_ledger.py`（新增）
- `openspec/specs/intent-routing/spec.md`（delta 改 2 条 scenario）
- `openspec/specs/engine-loop/spec.md`（delta 改 3 处引用）

**不动的部分**（架构稳定区）：
- engine 状态机 / LLM 工具循环 / router Protocol / `EngineDeps` DI 边界 / `chapter_summaries.json` 已有 schema
- `safe_path()` 越界防护（继续用于新工具的路径访问）
- 4 层架构 + 兼容层（`writer.agent`）结构

**迁移路径**：
- 现有项目无 `伏笔.yaml` 时：`foreshadow_search` 走"空 ledger + 提示"路径，不报错，输出"暂无伏笔记录，请先用 `/init` 或 `writer new` 初始化"
- 旧 ledger 存在但无新 schema：本次不提供自动迁移；新工具检查文件存在性 + 必要字段（`id` / `status`），缺字段时返回 `ToolResult(output="伏笔 ledger 格式不兼容，请手动迁移到新 schema")`
- 旧 `ProjectSearch` 用户（如果有外部脚本依赖 RAG 召回）：**无迁移路径**——RAG 召回在 HashEmbeddings 下本就不可用，删除后用户改用 `safe_read_file` 整篇读

**风险**：
- Medium：`foreshadow_search` 改了工具名和参数 shape，路由 spec 必须同步改 delta，否则测试 fail
- Low：删除 `faiss-cpu` 后 `langchain-community` 是否还有别处使用需要 audit
- Low：现有 27 个 `tests/` 文件中可能有间接 import `writer.rag` 的—— apply 前必须全量 grep 确认
