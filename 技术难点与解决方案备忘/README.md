# 技术难点与解决方案备忘

> **2026-07-14 重大修订**：本文原版本以 LangGraph 状态图 + RAG + 金字塔记忆为业务核心，伪代码走 `writer_graph.invoke`，与代码 `EngineSession.run_turn → Engine.run` 路径不符。
>
> 截至 2026-07-14，本项目实际形态是 **Engine.run 事件流 + IntentRouter Protocol + Markdown SKILL.md directives + 9 个 builtin Tool + ReActAgent 多步循环 + LangGraph `write_chapter` 工作流（PR2 实装）+ 中文项目目录**。本 README 顶部重写为真源，下方 17 篇备忘各自标记其与当前形态的关系；过期但仍有历史价值的部分（01 / 03 / 04 / 16 / 17 等）保留为「演进历史」参考。

---

## 业务需求理解

本项目是面向中文长篇小说创作的 CLI Agent。用户通过 REPL 与命令行工具完成从项目初始化、题材定位、大纲生成、目录生成、章节写作、审核、修订到跨章节检查的完整闭环。

核心业务要求：

- 项目目录采用**中文统一结构**（`大纲/`、`草稿/`、`正文/`、`人物/`、`世界观/`、`备忘/`、`创意/`），以 `AGENT.md` 作为唯一状态总览。
- `大纲/大纲.md` 是唯一正典大纲，正文生成必须遵循大纲、人物、世界观、伏笔和史实。
- 命令拦截矩阵**已删除**（per `chg-remove-state-machine-enforcement`，2026-07-12）；`ProjectState` 是 `/状态` 展示层，命令在任意状态可调用；「已存在 vs 新建 / 追加 vs 覆盖」由 SKILL.md body 的 LLM 自主判断。
- 长任务编排由 LangGraph `StateGraph` 实装：`write_chapter` 是 5 节点图 `prep_context → plan_chapter → draft_chapter → proofread → review_gate → (rewrite | persist_outputs)`；`review_chapter` 当前为占位 stub（PR3 待替换）。
- 长程上下文由 **4 层文件拼装 + `chapter_summaries.json` 切片**（per `writer/prompts/context.py::prep_context`）承担；RAG / FAISS / BM25 已删除（`chg-remove-rag`，2026-07-08）。
- CLI 具备流式输出、多行输入、Tab 补全、确认、interrupt 协议和可观测性。

## 真实全局入口（截至 2026-07-14）

```python
# REPL / CLI 调用方
session.run_turn(user_input)
    # EngineSession.run_turn() 构造 EngineContext + 委派给 session.engine.run(ctx)
        ↓
Engine.run(ctx)  # src/writer/engine/engine.py
    async for event in self._engine_loop(ctx):
        # 1. deps.route(user_input, project_state) → AgentAction
        # 2. match action.action_type 分派：
        #    - answer_directly     → Done(answered)
        #    - run_command         → _run_init_command | _run_directive | Done(command_pending)
        #    - call_tool           → _run_tool(rule-only) | _run_tool_loop(LLM)
        #    - start_workflow      → _run_workflow → Done(workflow_completed | aborted)
        #    - ask_user            → Interrupt + Done(ask_user)
        # 3. 三层 except：ToolError / SkillError / Exception → ErrorEvent + Done(aborted)
```

引擎主入口是 **`Engine.run(ctx)`**（`src/writer/engine/engine.py`），不是旧文档的 `run_engine`。`engine/loop.py::run_engine` 仅为 compat shim：每次构造临时 `Engine(deps, cfg)` 委派给 `engine.run(ctx)`。新代码应直接用 `Engine.run`。

## 备忘录清单

> 每篇标记状态：**current**（与代码一致）/ **mostly current**（主路径一致，细节需补）/ **historical**（保留作演进参考，关键决策已迁移）/ **stale**（已被其他文档取代，可读但不引用）。

### 引擎层

- [01-项目状态机与命令可用性](./01-项目状态机与命令可用性.md) — **historical**。`ProjectState` 退化为展示层；`validate_command_available` 已删除；2026-07-12 `chg-remove-state-machine-enforcement` 落地。
- [02-正典文件与多源写入一致性](./02-正典文件与多源写入一致性.md) — **mostly current**。中文目录统一后仍是正典文件约定；`safe_write_file` 3-stage guard 与 `AGENT.md` 题材行 merge 仍生效。
- [03-长篇上下文管理与RAG检索](./03-长篇上下文管理与RAG检索.md) — **historical**。RAG / FAISS / BM25 / 中文嵌入已删除（`chg-remove-rag`）；上下文改由 `prompts/context.py::prep_context` 4 层文件拼装 + `chapter_summaries.json` 切片。

### 长任务编排

- [04-LangGraph多阶段编排与子代理隔离](./04-LangGraph多阶段编排与子代理隔离.md) — **mostly current**。`write_chapter` 已实装 LangGraph 5 节点图（per `real-writing-pipeline` PR2）；`history_check` 节点当前未启用（未来扩展点）。文档首行 banner 已注明 2026-07-09 修订，但 `history_check` 仍按 future 描述，可读但勿当 spec。
- [05-LLM提供商路由与流式输出](./05-LLM提供商路由与流式输出.md) — **mostly current**。双 provider 路径（native `bind_tools` + JSON-prompt）仍生效；新增 `prose_client`（`RealProseClient` / `DeterministicProseClient`）装配在 `production_deps`，用于工作流而非前台 router。
- [06-长任务质量控制与自动回流](./06-长任务质量控制与自动回流.md) — **mostly current**。`REVIEW_THRESHOLD=7`、`max_retries=2`、`review_gate` 条件边 `rewrite | end` 是当前实装；`review_chapter` 仍待 PR3 替换。

### Tool 层

- [07-工具注册与文件权限安全](./07-工具注册与文件权限安全.md) — **current**。9 个 builtin Tool、`ToolRuntime.safe_path()` 白名单、`AGENT.md` 3-stage guard、`ToolError` 领域异常、`@runtime_checkable Protocol` 全部生效。
- [13-核心Tool设计](./13-核心Tool设计.md) — **current**。builtin Tool 完整签名与跨边界实现要点。

### CLI / REPL

- [08-REPL交互体验与命令解析](./08-REPL交互体验与命令解析.md) — **mostly current**。框架命令 + engine 委派路由原则未变；REPL `/init <brief>` 多选题材（2026-07-13）需补。
- [14-LLM用户交互与REPL中断协议](./14-LLM用户交互与REPL中断协议.md) — **mostly current**。`Interrupt` 事件 / `pending_interrupt` / REPL driver 拼多轮的协议未变；LangGraph interrupt 仍是未来工作流级 resume。

### 题材 / Agent

- [09-历史题材史实校验](./09-历史题材史实校验.md) — **mostly current**。`history_check` 工作流节点当前未启用；`史实/` 目录 + `apply_genre_scaffolding` 仍是历史题材基线。
- [15-LangChain前台调度Agent设计](./15-LangChain前台调度Agent设计.md) — **mostly current**。`IntentRouter` Protocol + `RuleBasedIntentRouter` / `LlmIntentRouter` / `CompositeRouter` 三实现 + `looks_like_command()` 触发条件仍生效。
- [16-Agent架构模式与本项目选型](./16-Agent架构模式与本项目选型.md) — **historical**。`writer.roles` 包已删除（`chg-remove-roles`，2026-07-09）；题材分支完全迁移到 `writer.agents._shipped/*.md` Markdown 范式；`process_init_brief` 是唯一保留的 Python-side capability。文档首行 banner 已注明 2026-07-09 修订，但 "Engine 层结构" 段落仍按旧 5 文件布局描述（实际 `src/writer/engine/` 多了 `engine.py` 主类）。

### 工作流 / 编排

- [10-伏笔生命周期与跨章节一致性](./10-伏笔生命周期与跨章节一致性.md) — **current**。YAML ledger + `foreshadow_search` Tool + 写章节时自动注入活跃伏笔（per `write_chapter._review_gate_node`）机制一致。
- [11-检查点恢复与可观测性](./11-检查点恢复与可观测性.md) — **historical**。LangGraph checkpointer（`SqliteSaver` / `MemorySaver`）已实装（2026-07-09 PR2），不再只是占位。文档可读作概念背景，但「节点结束写 SQLite checkpoint」表述需替换为「LangGraph 自带 checkpointer + EngineSession 维护 turn 历史」。
- [12-RAG与检索实现方案](./12-RAG与检索实现方案.md) — **historical**。RAG / FAISS 已删除（`chg-remove-rag`）；检索由 `foreshadow_search`（ledger 检索）+ `project_search`（行级 grep）承担；4 层文件拼装替代金字塔记忆。

### 系统编排

- [17-七种系统编排方式与本项目落地映射](./17-七种系统编排方式与本项目落地映射.md) — **historical**。`workflow_pending` 不再是合法 `DoneReason`（替换为 `aborted + decision`）；`run_engine` 改为主类 `Engine.run`；Markdown directive 是 Prompt Chaining 的本项目落地仍生效。