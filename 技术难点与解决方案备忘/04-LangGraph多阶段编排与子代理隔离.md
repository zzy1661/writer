# LangGraph 多阶段编排与子代理隔离

> **2026-07-14 重要修订**(覆盖 2026-07-09 修订):本文档原描述基于 LangGraph `StateGraph` 的章节写作主图(`plan_outline` → `write_chapter` → `proofread` → `history_check` → `review_gate`)。截至 2026-07-09 (`real-writing-pipeline` PR2 apply),`write_chapter` **已实装**为 LangGraph 5 节点图 `prep_context → plan_chapter → draft_chapter → proofread → review_gate → (rewrite | persist_outputs)`(代码 `src/writer/workflows/write_chapter.py`);`review_chapter` 仍为占位 stub,等 PR3 用同模式替换。
>
> **2026-07-14 二次修订**: `plan_chapter` 节点由纯确定性 beats 模板升级为 LLM 驱动的自由散文式计划。Deterministic 模式(`prose_client.name == "deterministic"`)严格拒绝,通过 raise `RuntimeError` 强制用户配置 `WRITER_API_KEY`。REPL 启动时检测 prose_client 是 deterministic 时打印软警告。
>
> **节点当前实现**(per `build_writer_graph()`):
> - `prep_context` — 调 `writer.prompts.context.prep_context` 组装 canon block;**纯确定性**
> - `plan_chapter` — LLM 自由散文式计划(deterministic 模式 raise RuntimeError 要求 WRITER_API_KEY);调 `deps.prose_client.generate_text` + `prompts.agents.CHAPTER_PLAN_TEMPLATE`
> - `draft_chapter` — 调 `deps.prose_client.generate_text`(real 路径)或确定性模板(deterministic 路径)
> - `proofread` — 长度 lint;**纯确定性**
> - `review_gate` — `deps.prose_client.name == "deterministic"` 路径以 score 8 自动通过;real 路径用 `ReviewVerdict` 结构化输出 + `deps.review_llm` 注入,阈值 `REVIEW_THRESHOLD=7`,未通过则回到 `draft_chapter`(`max_retries=2`)
> - `persist_outputs` — 写 `草稿/chapter-<chapter_id>.md` + 原子更新 `chapter_summaries.json`;**纯确定性**
>
> **checkpointer**:`_build_checkpointer(project_root)` 优先 `SqliteSaver`(`<root>/.writer/checkpoints.sqlite`),降级到 `MemorySaver`;`thread_id` 用 `session_id` 或 `f"write-{chapter_id}"`。
>
> **历史题材分支**:`history_check` 工作流节点本次**不做**(per 备忘 09 留作未来);LLM 通过 `AGENT.md` 的 `题材: 历史` 行 + `史实/` 目录推断题材,review_llm 自行决定是否读取史实。
>
> 本节其余部分(伪代码 + 验收标准 + 双轴映射)保留作概念参考,实现细节以 `src/writer/workflows/write_chapter.py` 为准。

## 业务背景

设计文档中同时存在两套概念:Planner、Outliner、Writer、Reviewer 是流程阶段,编剧顾问、历史顾问、校对是执行角色。写一章时需要编剧生成,再经校对、历史检查和综合审核。

## 技术难点

如果把阶段和角色混在一起,流程会变得难以扩展。例如历史顾问只在历史题材加载,但它不是一个固定阶段的替代品;校对只关心语言问题,不应看到全部创作上下文。多 Agent 共享上下文还会增加 token 浪费和角色越权风险。

## 解决方案(设计稿,待 LangGraph 落地)

使用 LangGraph 状态图表达阶段,用角色 prompt 表达执行身份:

- `plan_outline`:编剧顾问负责生成大纲或章纲。
- `write_chapter`:编剧顾问负责写正文。
- `proofread`:校对负责错别字、语病、格式。
- `history_check`:历史顾问仅在历史题材启用。
- `review_gate`:综合审核汇聚各报告并决定是否回流。

状态图控制流转,角色模板控制 LLM 行为。不同节点只读取自己需要的 `ContextPack` 子集。

> LangGraph 落地路径:`RunnerDeps.workflow_starter: WorkflowStarter`(当前未声明,等扩展)→ `WorkflowStarter.start(name, ctx, *, fresh=True)` AsyncGenerator → 在 `_engine_loop` 的 `start_workflow` 分支接进来,替换现在的 sync `_run_workflow` stub。LangGraph 自带 `MemorySaver` / `SqliteSaver` checkpoint 与 `interrupt` 协议,无需重新发明。

## 最小 demo / 伪代码

```python
from typing import Literal, TypedDict


class WriterState(TypedDict):
    chapter_id: str
    is_historical: bool
    draft: str
    review: dict
    retry_count: int


def write_chapter(state: WriterState) -> dict:
    draft = call_role_llm(role="story_agent", task="write", state=state)
    return {"draft": draft}


def proofread(state: WriterState) -> dict:
    report = call_role_llm(role="proofreader", task="proofread", state=state)
    return {"review": {"proofread": report}}


def route_after_proofread(state: WriterState) -> Literal["history_check", "review_gate"]:
    return "history_check" if state["is_historical"] else "review_gate"


def review_gate(state: WriterState) -> Literal["write_chapter", "end"]:
    if state["review"].get("needs_rewrite") and state["retry_count"] < 3:
        return "write_chapter"
    return "end"
```

## 核心依赖版最小代码

```python
from langgraph.graph import END, StateGraph


def build_writer_graph():
    graph = StateGraph(WriterState)

    graph.add_node("write_chapter", write_chapter)
    graph.add_node("proofread", proofread)
    graph.add_node("history_check", history_check)
    graph.add_node("review_gate", merge_review)

    graph.set_entry_point("write_chapter")
    graph.add_edge("write_chapter", "proofread")
    graph.add_conditional_edges(
        "proofread",
        route_after_proofread,
        {
            "history_check": "history_check",
            "review_gate": "review_gate",
        },
    )
    graph.add_edge("history_check", "review_gate")
    graph.add_conditional_edges(
        "review_gate",
        review_gate,
        {
            "write_chapter": "write_chapter",
            "end": END,
        },
    )

    return graph.compile()
```

## 落地建议

- 定义统一 `WriterState`,字段包含 `stage`、`role`、`context`、`draft`、`review`、`retry_count`、`is_historical`。
- 节点函数只返回 state diff,文件副作用集中到仓储服务。
- `history_check` 使用条件边,非历史题材直接跳到 `review_gate`。
- 每个角色 prompt 单独存放,项目级 prompt 可覆盖内置 prompt。

## 验收标准

- 非历史题材写作不会加载历史顾问上下文。
- `review_gate` 可以根据审核结果把流程回流到 `write_chapter`。
- 校对节点无法改写情节,只输出 diff 或问题报告。
- 新增角色或阶段时不需要重写 CLI 命令层。
