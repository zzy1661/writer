# Agent 架构模式与本项目选型

## 问题

当下主流的 Agent 架构模式有哪些?本项目为什么选择目前的形态?在不同抽象层之间如何保持职责清晰?

## 业务背景

Writer Agent 面向的是中文长篇小说的连续创作。用户的一次输入可能是确定命令,也可能是自然语言;落地的执行可能是秒级的伏笔查询,也可能是分钟级的章节写作。如果只用一种 Agent 范式,要么反应不够“轻”,要么长任务不够“稳”,两者会互相牵制。

文档 `15-LangChain前台调度Agent设计.md` 与 `04-LangGraph多阶段编排与子代理隔离.md` 已经分别描述了前台与后台,本文从更宏观的视角对比常见 Agent 架构模式,回答本项目为什么采用“前台调度 Agent + 后台 LangGraph 工作流 + 角色化节点 + 业务 Tool”这种混合形态。

## 技术难点

- 不同范式适合不同任务粒度,但是一个 Agent 实例很难同时兼容“毫秒级分发”与“分钟级长跑”。
- 长任务如果也交给单一 LLM Agent 自己决策循环,会出现调试困难、状态不可恢复、上下文无限增长的问题。
- 多 Agent 协同如果不约束共享状态,容易出现角色越权、重复劳动和 token 浪费。

## 解决方案总览:分层而不是单 Agent

本项目并不追求“一个万能 Agent”。它把工作切成三层,每层选择最适合的范式:

| 层级 | 主要范式 | 职责 | 典型组件 |
| --- | --- | --- | --- |
| 前台调度层 | 结构化输出 ReAct(可降级到规则版) | 把用户输入转成 `AgentAction` | `IntentRouter`(`RuleBasedIntentRouter` 当前 MVP) |
| 工作流编排层 | 计划-执行-审核图(Plan-Execute-Review Graph) | 推进章节写作、审核、回流 | LangGraph `StateGraph` |
| 业务工具层 | Tool-use(语义化 Tool) | 文件读写、伏笔、登记、统计等 | `chapter_register`、`foreshadow_update` 等 |
| 记忆与检索层 | RAG + 金字塔摘要 | 为长任务压缩上下文 | `build_context_pack` |

下文先介绍常见 Agent 架构,再解释为什么这种分层组合最适合本项目。

## 常见 Agent 架构模式

### 1. ReAct(Reason + Act)

Yao 等人 2022 年提出。核心循环是 `Thought → Action → Observation → Thought ...`。LLM 在每一轮先“思考”为什么做、调用什么工具,观察工具结果后再决定下一步。

优点:

- 实现简单,适合短链路决策。
- 自然语言思考过程留下可读轨迹,便于调试。

缺点:

- 没有显式全局计划,容易走弯路、重复调用、重读上下文。
- 长任务容易“上下文爆炸”。
- 不擅长需要并行或条件分支的工作。

伪代码示意:

```python
def react_loop(llm, tools, user_input, max_steps=8):
    history = [user_input]
    for _ in range(max_steps):
        thought = llm.think(history, available_tools=tools)
        action = llm.choose_tool(thought, tools)
        if action.is_final_answer:
            return action.answer
        observation = tools.call(action.name, action.args)
        history.append((thought, action, observation))
    raise TimeoutError("ReAct 未在限定步数内收敛")
```

### 2. Plan-and-Execute / Plan-and-Solve

Wang 等人 2023 年提出。先让 LLM 生成一个完整计划,然后按步骤执行。Plan-and-Solve 在此基础上要求显式求解子问题。

优点:

- 计划显式可见,便于人工审阅和缓存。
- 中途执行出错时,可以只修复某一步而不是重跑全部。
- 适合多步、有依赖的长任务。

缺点:

- 计划本身可能错误或粒度不当,需要质量控制。
- 对计划生成质量依赖较强。

伪代码示意:

```python
def plan_and_execute(llm, executor, user_input):
    plan = llm.make_plan(user_input)  # ["检索大纲", "生成章纲", "写正文", "校对"]
    results = {}
    for step in plan:
        try:
            results[step] = executor.run(step, results)
        except ToolError as exc:
            plan = llm.replan(plan, step, exc, results)
    return results[plan[-1]]
```

### 3. ReAct + Plan 混合(Plan-then-Act ReAct)

实际工程中,ReAct 与 Plan-and-Execute 经常组合使用:先生成计划,再以 ReAct 的方式执行每一步,并允许局部重新计划。本项目的工作流层就是这种思路。

### 4. Reflexion(自我反思)

Shinn 等人 2023 年提出。在 ReAct 之外增加一个“反思”环节,把每轮结果写回长期记忆,下次执行时参考。适合需要多轮迭代、提升成功率的 Agent。

适合用在:审核-回流的循环节点上,例如本项目的 `review_gate` 决定是否回流到 `write_chapter`。

### 5. Multi-Agent / 角色协作

多个 Agent 实例按角色协同,常见结构:

- 对等通信(每个 Agent 能直接给其他 Agent 发消息)。
- 总线式共享消息队列(AutoGen 风格)。
- 监督者 / 主管(Supervisor / Hierarchical Agent)统一分发任务。

适合:角色边界清晰、任务可分解、彼此可以并行处理的场景。

风险:共享可变状态、上下文不可控、token 浪费、调试困难。

### 6. Supervisor / Hierarchical Agent

上层有一个 Supervisor Agent 决定任务分发给哪个 Worker;Worker 完成后把结果汇报给 Supervisor,Supervisor 再决定下一步。LangGraph 的 `Supervisor` 模板就是这种思路。

适合:任务类型多、需要动态路由的场景。

### 7. Graph / State Machine Agent

把 Agent 的流转表达为一张图,节点是 LLM 调用或 Tool 调用,边是条件路由。LangGraph 是典型代表。可以组合上述各种范式作为节点行为。

优点:

- 流程可见、可测试、可持久化、可恢复。
- 自然支持条件分支、并行、回流。
- 与业务状态机贴合。

缺点:

- 抽象成本高,小任务过度设计。

### 8. Tool-Use(工具调用)与 RAG Agent

Tool-Use 本身不是 Agent 范式,但是大多数 Agent 都依赖它。RAG Agent 把外部检索结果作为上下文片段输入给 LLM。

适合:本项目的伏笔检索、史实校验、人物查询都依赖这条线。

## 本项目采用的混合架构

综上所述,本项目**没有押注单一范式**,而是按任务粒度组合:

- **前台**:结构化输出的轻量 Agent(`IntentRouter`,MVP=`RuleBasedIntentRouter`)
  - 主范式:Plan-and-Execute 的退化版 + 结构化输出
  - MVP 可以退化为规则版,保证高频命令稳定
  - 只产出 `AgentAction`,不直接动手
- **后台**:LangGraph 状态图(Plan-Execute-Review 图)
  - 主范式:Graph Agent,节点内可套 ReAct 或 Reflexion
  - 多角色(编剧/校对/历史/审核)由 prompt 区分,**不通过独立进程通信**
  - 通过条件边与回流边支持 Plan、Replan、Reflect
- **工具层**:语义化 Tool(`read_file`、`chapter_register` 等)
  - 主范式:Tool-Use,但只允许调用项目注册的业务 Tool
- **记忆层**:RAG + 摘要 + 状态文件
  - 主范式:RAG Agent,数据来自正典文件、伏笔库、人物库等
- **角色层（题材分支）**:每个题材一个 `StoryConsultant` 子类（[OpenSpec `fea-genre-aware-init`](../../openspec/changes/fea-genre-aware-init/proposal.md) 2026-07-06）
  - `HistoryConsultant` / `XuanhuanConsultant` / `RomanceConsultant` / `StoryConsultant`(兜底)
  - 通过 `EngineDeps.story_consultant` 槽位按 `AGENT.md` `题材:` 行动态派生
  - 每个子类的 `chapters` 字符串前缀约定表达题材差异

这五个层级分别对应不同的范式,但共同遵循几个原则:

1. **不把长任务交给前台 Agent。** `start_workflow` 一旦返回,前台就不再干涉,由 LangGraph 接管。
2. **不引入独立的多 Agent 实例通信。** 多个角色通过 LangGraph 节点的 prompt 模板切换,而不是各自拥有独立进程;它们看到的上下文由 `ContextPack` 裁剪。
3. **状态机先于 Agent。** ProjectState 是 S0-S5 大状态机,Agent 在其下工作;`validate_command` 拦截所有不符合状态的指令。
4. **Tool 是 Agent 的边界。** 任何文件副作用必须经过注册过的 Tool,避免 LLM 直接编辑 Markdown。

## 设计思路对照

| 项目要求 | 单 Agent 范式难以满足的原因 | 本项目做法 |
| --- | --- | --- |
| 高频命令毫秒级响应 | 单一 ReAct 每次都要把历史塞满 prompt | 前台调度 Agent 只关心命令路由,工作流交给后台 |
| 长章节写作分钟级稳定 | ReAct 容易走偏,token 越长越慢 | 走 LangGraph 显式计划与节点 |
| 角色不能越权 | 多 Agent 共享消息总线容易泄露上下文 | 每个节点只读自己需要的 `ContextPack` |
| 审核失败要回流 | 单 Agent 没有显式回流边 | `review_gate` 通过条件边回 `write_chapter` |
| 状态可恢复 | ReAct 历史不可序列化检查点 | LangGraph 自带 checkpoint + Tool 调用历史 |
| 历史题材可选加载 | ReAct 不知道是否加载历史顾问 | 通过 `is_historical` 条件边控制 |

## 最小 demo / 伪代码

下面给出一个把四种范式组合在一起的端到端最小骨架:

```python
from typing import Literal

from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel


# ---------- 1. 前台:结构化输出调度 Agent (Plan-and-Route) ----------
ActionType = Literal["start_workflow", "call_tool", "ask_user", "answer_directly"]


class AgentAction(BaseModel):
    action_type: ActionType
    workflow: str | None = None
    tool_name: str | None = None
    arguments: dict = {}
    answer: str | None = None


COMMAND_AGENT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
你是 Writer Agent 的前台调度 Agent。
把用户输入转成 AgentAction,不要直接动手。
- 长任务 -> start_workflow
- 轻量查询 -> call_tool
- 信息不足 -> ask_user
- 直接回答 -> answer_directly
""",
        ),
        ("human", "项目状态:{state}\n用户输入:{input}"),
    ]
)


def build_router(llm):
    """Factory for the future ``LlmIntentRouter`` (LangChain structured output)."""
    return COMMAND_AGENT_PROMPT | llm.with_structured_output(AgentAction)


# ---------- 2. 后台:LangGraph 工作流 (Plan-Execute-Review Graph) ----------
class WriterState(BaseModel):
    chapter_id: str
    is_historical: bool = False
    plan: list[str] = []
    draft: str = ""
    review: dict = {}
    retry_count: int = 0


def plan_node(state: WriterState) -> dict:
    plan = ["plan_outline", "write_chapter", "proofread"]
    if state.is_historical:
        plan.append("history_check")
    plan.append("review_gate")
    return {"plan": plan}


def write_node(state: WriterState) -> dict:
    # 这里通常配合 ReAct 子循环或单次 LLM 调用
    return {"draft": f"<{state.chapter_id} 草稿>"}


def proofread_node(state: WriterState) -> dict:
    return {"review": {**state.review, "proofread": "ok"}}


def history_check_node(state: WriterState) -> dict:
    return {"review": {**state.review, "history": "ok"}}


def review_gate_node(state: WriterState) -> Literal["write", END]:
    needs_rewrite = False  # 由 LLM 审核结果决定
    if needs_rewrite and state.retry_count < 3:
        return "write"
    return END


def build_writer_graph(llm):
    g = StateGraph(WriterState)
    g.add_node("plan", plan_node)
    g.add_node("write", write_node)
    g.add_node("proofread", proofread_node)
    g.add_node("history_check", history_check_node)
    g.add_node("review_gate", review_gate_node)

    g.set_entry_point("plan")
    g.add_edge("plan", "write")
    g.add_edge("write", "proofread")
    g.add_conditional_edges(
        "proofread",
        lambda s: "history_check" if s.is_historical else "review_gate",
        {"history_check": "history_check", "review_gate": "review_gate"},
    )
    g.add_edge("history_check", "review_gate")
    g.add_conditional_edges(
        "review_gate",
        review_gate_node,
        {"write": "write", END: END},
    )
    return g.compile()


# ---------- 3. 业务 Tool 层 ----------
@tool
def chapter_register(chapter_id: str, title: str, draft: str) -> str:
    """把章节正文登记到正文草稿目录。"""
    return f"正文草稿/{chapter_id}_{title}.md"


tool_node = ToolNode([chapter_register])


# ---------- 4. 记忆 / RAG 层(伪代码) ----------
def build_context_pack(chapter_id: str) -> dict:
    """从正典文件中裁剪与 chapter_id 相关的子集。"""
    return {
        "outline_slice": "...",   # 大纲中相关条目
        "foreshadow": [...],      # 伏笔库中相关条目
        "persona": [...],         # 人物库中相关条目
    }
```

可以看到:

- 前台 `IntentRouter` 用的是 **Plan-and-Route + 结构化输出**(协议,实现可换);
- 后台工作流是 **Graph Agent**,内含条件分支与回流(Plan-Execute-Review);
- 节点内允许嵌套一次小的 ReAct(写作环节可能多轮查询伏笔);
- 业务 Tool 由 `tool_node` 统一封装,RAG 上下文由 `build_context_pack` 提供。

## 与已有文档的关系

- 与 `04-LangGraph多阶段编排与子代理隔离.md` 互为补充:本文讲“为什么选这种范式”,该文讲“怎么搭图”。
- 与 `15-LangChain前台调度Agent设计.md` 互为补充:本文把前台 Agent 放回整个架构对比中,该文给出具体实现。
- 与 `13-核心Tool设计.md` 互为补充:本文讲 Tool-Use 在整体 Agent 中的位置,该文给出 Tool 清单与安全约束。
- 与 `01-项目状态机与命令可用性.md` 互为补充:ProjectState 是 Agent 行动的先决条件,任何 Agent 操作都必须先经过状态校验。

## 落地建议

- 不要尝试用一个 LangChain Agent 完成所有任务。命令分发交给前台 Agent,写作交给 LangGraph,文件副作用交给 Tool。
- 不要让多角色变成多进程。角色之间的差异由 prompt 区分,上下文通过 `ContextPack` 裁剪,而非共享可变内存。
- 引入新范式前先问:它解决的是哪一层的痛点?是前台路由、长任务编排、还是反思回流?混用要明确边界。
- 把每种范式的特征(思考轨迹、计划、反思)落盘:计划写到 `大纲/`,反思历史写到 `修订/`,便于后续训练或调试。
- MVP 阶段保留规则版 `route()` 作为 primary(配合 `CompositeRouter` 包装 LLM fallback),避免 LLM 把 `/写作` 误识别为说明性问题。

## 已落地的 Engine 层结构（v0.1）

备忘 16 给出的是 4 层概念模型。本节把"前台调度层 + 后台工作流层"具体落到 `writer.engine` 包的代码形态,后续接 LangGraph 时按这个边界对齐。

### 5 文件布局

```
writer/engine/
├── __init__.py    # 公共门面: 只 re-export, 不放逻辑
├── events.py      # Event 数据类层级(frozen=True, 单一基类)
├── context.py     # EngineContext(frozen) — 单一输入契约，2026-07-05 m4 删除 EngineState 后
├── deps.py        # EngineDeps Protocol + production_deps()
├── config.py      # EngineConfig(frozen, "环境冰封")
└── loop.py        # run_engine() + _engine_loop() AsyncGenerator
```

每个文件的职责:

| 文件 | 输入 | 输出 | 是否可变 | 谁拥有 |
|---|---|---|---|---|
| `events.py` | — | Event 子类层级 | 不可变 (frozen dataclass) | 全局共享 |
| `context.py` | 用户调用 | `EngineContext` 实例 | 不可变 (frozen) | 当次 turn |
| `deps.py` | DI 边界 | `EngineDeps` 协议 + 默认实现 | 不可变 (Protocol + dataclass) | 长生命周期 / session 级 |
| `config.py` | ctx + 运行时 | `EngineConfig` 实例 | 不可变 (frozen) | 当次 turn |
| `loop.py` | ctx + deps + config | AsyncIterator[Event] | — | 当次 turn |

### 两种"状态对象"的切分原则

不把 `EngineContext` 和 `EngineConfig` 揉成一坨,是因为它们在生命周期和写入权限上不一样:

- **`EngineContext` (frozen)**: 当次 turn 的全部输入,函数参数。LLM / LangGraph 任何外部输入都只能写进这个,不能写 loop 内的可变状态。
- **`EngineConfig` (frozen)**: 一次 turn 内不变的运行时配置(session_id、fast_mode 等)。Mirrors Claude Code §八"环境冰封"——消费者在 AsyncGenerator 流式消费事件时,config 不会突变,可放心依赖。

> **2026-07-05 修订 (m4)**: 早期版本还有第三个 `EngineState`(mutable,engine 内部跨迭代状态)。MVP 阶段从未实例化,且字段 `transition` 也从未被任何代码引用——属于死代码。删除后,所有 input contract 全部 frozen,engine 内部不再持有可变状态(loop 是纯 AsyncGenerator)。若未来需要"retry_count"等跨迭代字段,优先放进 `EngineSession`(writer/session),不在 engine 内引入可变状态。

### Engine 是无状态 AsyncGenerator

`run_engine(ctx, deps, *, config)` 返回 `AsyncIterator[Event]`,本身不持有任何会话状态。原因:

1. **流式消费友好**: REPL `async for event` 逐事件渲染,token-level 流式输出可直接接。
2. **取消成本低**: REPL Ctrl+C 可以中断 async iteration,engine 不持有需要清理的资源。
3. **session 可任意 restart**: 重连 session 不需要重置 engine 内存,只需重新调用 `run_engine`。
4. **易测**: 单个 turn = 单次 AsyncGenerator 消费,test 直接 `async for` 就行。

会话级状态(对话历史、checkpoint、session 内存)属于 `EngineSession`(per 17 预留),不在 engine 内部。

### EngineDeps Protocol 的扩展点

`EngineDeps` 协议 MVP 只声明 `router`,但留好了扩展位置:

```python
@runtime_checkable
class EngineDeps(Protocol):
    router: IntentRouter     # MVP 注入点

    # 后续按需扩展:
    # tool_registry: ToolRegistry       # per 13
    # workflow_starter: WorkflowStarter # per 04
    # interrupt_handler: InterruptHandler  # per 14
    # stop_hooks: StopHookRegistry      # Claude Code §十二 12.3
    def route(self, user_input: str, project_state: str) -> AgentAction: ...
```

`production_deps()` 默认用规则版 router 实例化 `_DefaultEngineDeps`。三处扩展点是 LangGraph 接 / Tool 接 / 中断 resume 接的入口,等相应轮次时再加进来,现在不预先堆。

### 与 Layer 表的对应

回头看 4 层模型,Engine 实际上跨越前台 + 后台两层:

- **前台调度层** → `engine.loop` 调 `deps.route()`,发 `ActionEvent` 后再分派
- **后台工作流层** → engine 内 `start_workflow` 分支现在占位 `Done(reason="workflow_pending")`,等 LangGraph 落地时把这个分支换成 `WorkflowStarter.start(workflow, ctx)`
- **业务工具层** → 同样的占位分支 `call_tool`,等 `engine.deps.tool_registry` 注入后换成真实调用
- **记忆层** → 现在还不在 engine, 由 `EngineSession`(per 17)管 checkpoint

## 更新后的验收标准

在原本六条之外,补充:

- Engine 包严格 5 文件布局,新增能力(workflow / tool / interrupt)只通过 `EngineDeps` 扩展,不直接改 `loop.py`
- `EngineContext / EngineConfig` 全程 frozen（2026-07-05 m4 删除 `EngineState` 后,所有 input contract 均不可变）
- `run_engine` 是 `AsyncIterator[Event]`,不持有会话状态
- `EngineDeps` 必须 `@runtime_checkable`,便于测试时 mock

## 验收标准

- 前台 Agent 输出一律是 `AgentAction`,不允许自由文本。
- 长任务只能由后台 LangGraph 执行,前台不直接推进 draft。
- 任何文件写入都通过业务 Tool,不能由 LLM 直接编辑 Markdown。
- 历史题材才会加载 `history_check` 节点,其他题材不会消耗相关 token。
- 审核结果可以决定是否回流到 `write` 节点,回流次数受 `retry_count` 上限保护。
- 在 `Plan-Execute-Review` 图中能清晰看到每个范式的位置:Plan(`plan` 节点)、Execute(`write`/`proofread`/`history_check`)、Review(`review_gate`)。

## 其他常见范式速查

- **BabyAGI / AutoGPT**:自主任务分解 + 循环执行,适合开放式探索,但可控性差,不适合本项目。
- **Toolformer 思路**:让模型在训练时学会何时调用工具,本项目不需要重新训练模型,所以用 prompt 引导 + Tool 列表约束。
- **Voyager 风格技能树**:运行中学到的技能写回工具库。本项目可以借鉴:成功的写作技巧沉淀为 Tool 或 prompt 片段。
- **RAG-Fusion / HyDE**:检索时多查询融合或假想文档检索,适合在本项目 RAG 层增强。
