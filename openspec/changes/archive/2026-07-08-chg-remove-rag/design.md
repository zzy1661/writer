## Context

当前 RAG 实现位于 `src/writer/rag.py`，被以下三处直接调用：
- `src/writer/context.py:133` — `prep_context()` 拼装 canon block 时
- `src/writer/tools/builtin/analysis_tools.py:112` — `ProjectSearch` 在精确匹配命中不足时
- `src/writer/tools/builtin/foreshadow_tools.py:23` — `ForeshadowQuery` 的唯一召回路径

`HashEmbeddings`（`rag.py:33-56`）是 sha256+bigram 的确定性占位实现，对中文改写后的同义表达召回率近 0；`ProjectRagIndex.query`（`rag.py:66-80`）每次都 `FAISS.from_documents()` 从零重建索引，无缓存、无 mtime 失效。

项目数据形态强结构化（`outline/` 整篇 < 5KB、`characters/` 整篇 < 50KB、`chapter_summaries.json` 已存在的预压缩摘要），50 万字规模 grep 完全可承受。Claude Code 范式（Grep/Glob/Read 工具集 + 让 LLM 决定何时调）已在 `tools/builtin/{file,locate,analysis}_tools.py` 中部分实现。

`langchain-openai>=0.2.0`（`pyproject.toml:19`）虽已就位，但本 change 不引入 LLM 依赖、不引入 embedding API——这是**只删不加**的纯减法 change。

## Goals / Non-Goals

**Goals:**
- 完全删除 `src/writer/rag.py` 模块及其全部公开 API
- 把三处 RAG 调用点替换为：(1) 纯文件拼装 / (2) 纯 grep / (3) 结构化 ledger 查询
- 引入 `foreshadow_search` 工具 + `伏笔.yaml` ledger 文件结构
- 让项目内召回"对齐 Claude Code 范式"——工具化、可观察、零外部依赖
- 删除 `faiss-cpu` 依赖；评估并删除 `langchain-community`（如果别处无引用）

**Non-Goals:**
- 不引入任何 embedding / 向量召回 / LLM 检索路径（即使 langchain-openai 已在依赖里）
- 不动 `chapter_summaries.json` 已有 schema
- 不动 engine 状态机、router Protocol、`EngineDeps` DI 边界
- 不动 `safe_path()` 越界防护——继续用于新工具的路径访问
- 不为旧项目提供自动迁移脚本（`伏笔.yaml` 缺失时新工具走"空 ledger"路径）
- 不引入 foreshadow ledger 的 CRUD 编辑器——本次只做"读 + 查询"，写入仍由未来 LLM 化或人工编辑 YAML

## Decisions

### 1. 删除 vs 保留 `src/writer/rag.py`

**决定：删除整文件。**

考虑过：保留 `split_chinese_markdown`（`rag.py:110-133`）给 `chapter_summaries` 摘要生成复用。结论：摘要生成已经在 `context.py` 内部直接处理（如果存在），不需要复用一个跨模块工具；且 `split_chinese_markdown` 实现可以原地挪到 `context.py` 私有函数。

**替代方案**：保留 rag.py 但只删 `HashEmbeddings`/`ProjectRagIndex`，转作"未来 RAG 实验场"。**否决**：没有 RAG 接口就没有保留理由；占位代码会随时间漂移。

### 2. `_build_canon_block` 重写策略

**决定：纯文件拼装，按层叠顺序 = system > 任务相关 canon > 历史 > 任务。**

```
canon_block = (
  outline/ 大纲.md 全文            # 小，整篇读
  + characters/ 全角色卡            # 小，整篇读
  + 章节摘要（chapter_summaries.json）按 chapter_id 切片 + 前后 N 章
  + 最近一章原文（manuscript/chapter-XXX.md）  # 给 LLM 看上一章的笔触
)
```

预算受 `trim_to_budget` 控制（`context.py:60-99`），新拼装必须保持总 token 上限可观察。`token_audit` 字段保持结构不变。

**替代方案**：让 LLM 在写章节前自己调 `safe_read_file` 拉 canon。**否决**：和当前"pre-bake context"架构冲突；`prep_context()` 的契约是"workflow 层拿 ready-to-use pack"，分散在多 turn 调工具不满足。

### 3. `foreshadow_search` 的 ledger 文件格式

**决定：YAML 存于 `<project_root>/伏笔.yaml`（中文文件名，与项目既有中文命名习惯一致，参照 `技术难点与解决方案备忘/`）。**

```yaml
# 伏笔 ledger schema v1
foreshadows:
  - id: F001
    tags: [玉簪, 旧匣子, 身世]
    status: paid          # laid | paid
    laid_chapter: 3
    paid_chapter: 47
    notes: 主角身世揭晓
  - id: F002
    tags: [反派, 卧底]
    status: laid
    laid_chapter: 12
    paid_chapter: null
    notes: 反派 A 真实身份
```

**理由**：
- YAML > JSON：人可手写、注释友好、字段顺序不重要
- 中文文件名 > `foreshadow.yaml`：与项目目录既有中文命名一致
- `paid_chapter: null` 支持未回收
- `tags` 数组支持多对多，且天然支持 grep 兜底

**替代方案 A**：`foreshadows.json`。**否决**：JSON 不可注释、无尾逗号、人手写易错。
**替代方案 B**：散落各章节文件 frontmatter。**否决**：跨章汇总需要重读所有文件，O(N) 且难分页。
**替代方案 C**：放进 `chapter_summaries.json`。**否决**：混杂两种 schema，未来扩展会脏。

### 4. `foreshadow_search` 工具签名

**决定：**

```python
class ForeshadowSearch:
    name = "foreshadow_search"
    description = "查询伏笔 ledger（伏笔.yaml），支持按 ID、tag、status、章节范围、关键字子串过滤。"

    def run(
        self,
        runtime: ToolRuntime,
        *,
        tags: list[str] | None = None,
        status: Literal["laid", "paid", "all"] = "all",
        chapter_range: tuple[int, int] | None = None,
        keyword: str | None = None,
        id: str | None = None,  # F001 这种
    ) -> ToolResult: ...
```

**参数优先级**（实现约束）：
- `id` 提供时 → 直接 lookup，单条返回
- `tags` 提供时 → 命中任一 tag 的条目
- `status="laid"` → 排除 `paid_chapter: not null`
- `chapter_range` 提供时 → 限制 `laid_chapter` 在范围内
- `keyword` 提供时 → 扫 `notes` / `id` / `tags` 字段的子串匹配（grep 兜底）

**空 ledger 行为**：`伏笔.yaml` 不存在或 `foreshadows: []` → `ToolResult(output="暂无伏笔记录，请先创建 伏笔.yaml 或在 /init 时生成")`，不报错。

**文件缺失/格式错误行为**：`yaml.YAMLError` 或缺 `foreshadows` 键 → `ToolResult(output="伏笔 ledger 格式不兼容（缺失 foreshadows 列表）", error="schema")`。

**替代方案**：保持单 `query: str` 参数，工具内部做解析。**否决**：失去 type safety；LLM 工具循环里 `with_structured_output` 难校验；Router 写 LLM prompt 时无法给清晰 schema。

### 5. 路由 spec 中的 `foreshadow_query` 引用

**决定**：保留 `call_tool` action_type + `foreshadow_search` 工具名，**只改工具名和参数 shape**。`intent-routing/spec.md` L17-19 和 L33-35、`engine-loop/spec.md` L21-26、L72、L75-76 都用 delta 形式更新。

router 行为本身不变（仍是 `call_tool` + tool_name + arguments 三元组）；这是**纯改名 + 改 schema** 的 delta，不动 router 实现。

### 6. 依赖审计

**决定：**
- 删 `pyproject.toml:28` 的 `faiss-cpu>=1.8.0`
- 检查 `langchain-community>=0.3.0`（L20）的全部 import 点；本 change 假设 `langchain-community` 别处还在用（仅 FAISS 部分不再需要），**apply 阶段 grep 确认**：
  - 命中除 `rag.py` 外的 `langchain_community` 引用 → 保留
  - 仅 `rag.py` 引用 → 一起删

**核验命令**（apply 前必跑）：
```bash
rg "langchain_community" src/ tests/
rg "from langchain" src/ tests/
```

预期：删 `rag.py` 后 `langchain_community` 还可能在 `tools/langchain_bridge.py` 引用（per `CLAUDE.md` 描述），不删；FAISS 一定可删。

### 7. 测试重写

**决定**：
- `tests/test_context_rag.py` 改名为 `tests/test_context.py`；断言从"RAG 召回能命中 F003"改为"canon block 包含 outline 全文 + character 全文 + 该章 summary"
- 新增 `tests/test_foreshadow_ledger.py`，覆盖：
  - 空 ledger（文件不存在 / `foreshadows: []`）→ 返回"暂无"提示
  - 单条 lookup by `id`
  - tag 过滤（任一命中 / 全命中两种 mode，**实现层只做任一命中**——更符合 LLM 工具使用直觉）
  - status=laid 排除已回收
  - chapter_range 过滤
  - keyword 子串兜底
  - 文件格式错误 → 友好错误输出而非 raise

## Risks / Trade-offs

[删除 RAG 后失去 embedding 模糊召回] → **Mitigation**：本项目没有真实可用的 embedding（HashEmbeddings 是占位），删后状态等价于"从来没有 RAG"；未来如果撞上 50 万→500 万字规模、或者引入外部语料参考书，可以重新加回，那时直接上 OpenAI 兼容 embedding（已有 `langchain-openai` 依赖）。

[工具改名 + 参数 shape 改破坏 router test fixture] → **Mitigation**：router test fixture 在 apply 阶段同步更新；`openspec validate --strict` 必须 pass 才算完成。

[伏笔 ledger YAML 格式可能演化] → **Mitigation**：在 YAML 顶部加 `# 伏笔 ledger schema v1` 注释，未来 v2 加 migration 段落；本次不引入版本字段，保持轻量。

[chapter_summaries.json 路径硬编码] → **Mitigation**：本次不动 `chapter_summaries.json` schema；`_build_canon_block` 按既有 `context.py:145-148` 路径读；任何 schema 升级留给后续 change。

[apply 阶段 `langchain-community` 引用 audit 可能发现新清理面] → **Mitigation**：audit 是 task 1.6；如发现 `langchain_community` 仅 `rag.py` 引用，扩展本 change 一并删除（注明原因）；否则保留。

## Migration Plan

**部署步骤**（apply 阶段顺序执行，见 `tasks.md`）：
1. 写 `foreshadow_ledger.py` 新模块（YAML 加载 + 查询函数）
2. 写新 `ForeshadowSearch` 工具类（替换 `foreshadow_tools.py`）
3. 重写 `context.py::_build_canon_block`
4. 改 `ProjectSearch` 删 RAG 兜底
5. 改 `tools/builtin/__init__.py` 重导出
6. 删 `src/writer/rag.py`
7. 改 `pyproject.toml`（删 `faiss-cpu`，audit `langchain-community`）
8. 改 router test fixture（`foreshadow_query` → `foreshadow_search`）
9. 改 `tests/test_context_rag.py` → `tests/test_context.py`
10. 新增 `tests/test_foreshadow_ledger.py`
11. 改 spec delta（`intent-routing/spec.md` + `engine-loop/spec.md`）
12. 跑 `uv run ruff check src tests && uv run mypy src/writer && uv run pytest` 全绿

**回滚策略**：`git revert` 整个 commit。RAG 删除是纯减法，无破坏性副作用，无数据迁移需要回滚。

**兼容窗口**：无。本 change 是 breaking，按 OpenSpec 流程 archive 时通过 `openspec sync` 同步到 main specs。

## Open Questions

1. **`foreshadow_search` 接受多个同时过滤条件时是 AND 还是 OR？** — 倾向 AND（更精确），但 LLM 工具循环里 LLM 一次性给全条件时不会混着用。可在 apply 阶段确认。
2. **`伏笔.yaml` 是否需要在 `writer new` / `/init` 时自动创建空模板？** — 倾向不创建（避免噪音目录），让 LLM 第一次用 `foreshadow_search` 触发"暂无伏笔"提示后再引导用户初始化。apply 阶段确认。
3. **`chapter_summaries.json` 是否要把伏笔信息反向引用进 `foreshadows`？** — 倾向不（本 change 不动 `chapter_summaries.json` schema）。未来可作为 `fea-foreshadow-cross-reference` 独立 change。
