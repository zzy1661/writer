# 长篇上下文管理与上下文拼装

> **2026-07-08 重要修订**:本文档原标题《长篇上下文管理与 RAG 检索》描述的是基于 FAISS + BM25 + 中文嵌入的混合检索方案。该方案已经在 [OpenSpec `chg-remove-rag`](../../openspec/changes/archive/2026-07-08-chg-remove-rag/) 落地过程中**整体删除**(归档路径 `openspec/changes/archive/2026-07-08-chg-remove-rag/`)。
>
> 删除原因:placeholder `HashEmbeddings` 在真实查询下召回接近零;结构化 ledger + 章节摘要已经覆盖 RAG 原本要填补的检索场景。本文档**不再代表项目当前实现**,仅作为历史设计留档。
>
> 后续如要补"长篇上下文管理"专题,请基于 `engine/context.py::_build_canon_block` 重写,把"金字塔记忆 + 动态 top-up"换成"4 层文件拼装 + 上下文预算裁剪"。

## 历史背景(留档)

### 业务背景(原文)

项目目标是辅助生成 20-50 万字长篇小说。章节越多,人物、伏笔、世界观、过往剧情越难一次性放入模型上下文,但写作又必须遵循全书正典。

### 技术难点(原文)

长篇写作的上下文既要全面,又要受 token 限制。只喂近几章会遗忘远期伏笔和人物弧光;全量喂正文会超预算、成本高、噪声大。不同节点的需求也不同:写正文需要前文节奏,校对需要当前正文,历史顾问需要史实索引。

### 历史解决方案(原文,已废弃)

采用 `prep_context` 前置节点,主节点不直接检索。上下文由静态骨架 + 动态 RAG top-up 组成:

- 静态骨架:角色 prompt、输出格式、当前任务。
- 正典检索:大纲、人物、世界观、伏笔、史实。
- 金字塔记忆:近 3 章详细摘要,中期章节简摘要,远期只保留人物/伏笔/信物状态。
- top-up:当章节涉及待回收伏笔、新人物、卷首章、重大信物时补充完整条目。

索引按项目隔离,FAISS 存向量索引,BM25 负责关键词补召回。

---

## 当前实现(2026-07-08 起)

### 上下文拼装 4 层

`writer/engine/context.py::_build_canon_block` 现在只做**纯文件拼装**,不再依赖任何向量索引:

| 层 | 来源 | 何时拼入 |
| --- | --- | --- |
| 1. 整篇 outline | `outline/大纲.md`(若存在) | 每次 context pack |
| 2. 整篇 characters | `characters/*.md` 同表 | 每次 context pack |
| 3. 章节摘要切片 | `chapter_summaries.json`(若存在) | 每次 context pack |
| 4. 最近一章原文 | `manuscript/<latest>.md` | 每次 context pack |

预算由调用方裁剪(LLM 工具循环注入 LLM 之前的预处理)。

### 检索替代:grep + 伏笔 ledger

- **`project_search`**(`writer/tools/builtin/analysis_tools.py`):Claude Code 风格的 Grep 模拟器,行级子串匹配,无嵌入、无向量兜底。覆盖"在项目目录中找关键词"的需求。
- **`foreshadow_search`**(`writer/tools/builtin/foreshadow_tools.py`):结构化查询 `<project_root>/伏笔.yaml`,支持按 `id` / `tags` / `status` / `chapter_range` / `keyword` 多条件 AND 过滤。覆盖"伏笔召回"的检索需求。

### S0 路径

未绑定项目时,`production_deps` 注入 sentinel `Path("/__no_project__")`。`project_search` 等路径工具会通过 `safe_path` 拒绝(走 `ToolDeniedError` → `Done(aborted)`);`foreshadow_search` 主动识别 sentinel 并返回友好提示(不走 abort),这是路径无关工具的预期行为。

### LangChain 角色

LangChain 在 L4(LLM Provider)+ L3(LLM tool loop 桥接)仍然使用;`writer/tools/langchain_bridge.py::_build_args_schema` 复用 `inspect.signature + get_type_hints + pydantic.create_model` 给 builtin Tools 生成 LC `StructuredTool.args_schema`。`LLMToolLoop` (`src/writer/llm/agent.py`) 用 native `bind_tools` 或 JSON-prompt 路径消费工具列表。

---

## 与 OpenSpec 的一致性

- 移除:`src/writer/rag.py` 整文件 + `pyproject.toml:28` `faiss-cpu>=1.8.0` 依赖
- 重命名:`foreshadow_query(query: str)` → `foreshadow_search(id / tags / status / chapter_range / keyword)`
- 主 Spec delta:`openspec/specs/foreshadow-ledger/spec.md` (NEW, 3 Requirements + 13 Scenarios)
- 路由 + 引擎 spec delta:`openspec/specs/intent-routing/spec.md` L17-19、L33-35 + `openspec/specs/engine-loop/spec.md` L21-26、L72、L75-76

## 后续 TODO(不在 chg-remove-rag 范围)

- 章节定稿后写 `chapter_summaries.json` 的写入路径(目前只读)
- `chapter_summaries.json` ↔ `伏笔.yaml` 交叉引用(决定 top-up 哪些条目)
- LLM 工具循环预算从 `MAX_LOOP_STEPS=5` 提到按 token 动态计算
- 真正的长上下文压缩(pyramid memory)何时启用,先观察章节数 / 摘要大小再决定