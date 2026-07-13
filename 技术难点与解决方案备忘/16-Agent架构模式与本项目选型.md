# Agent 架构模式与本项目选型

> **2026-07-14 重要修订**(覆盖 2026-07-09 修订):本文档原版本以 `writer.engine.loop.run_engine` 为主入口 + `_DefaultEngineDeps.run_workflow` 占位 stub 为基础。截至 2026-07-13,**`Engine` 类已成为引擎主入口**(`src/writer/engine/engine.py`),`Engine.run(ctx)` 公开 API;`engine.loop.run_engine` 降级为 compat shim(每次构造临时 `Engine(deps, cfg)` 委派给 `engine.run(ctx)`)。
>
> **`Engine` 类形态**(per 2026-07-13 重构):
> - 主类:`Engine` 持 `EngineDeps`(DI 容器,长生命周期)+ `EngineConfig`(per-loop 配置)
> - 公开方法:`Engine.run(ctx) -> AsyncIterator[Event]` / `Engine.replace_deps(new_deps)` / `Engine.replace_cfg(new_cfg)`
> - 私有 helper:`_engine_loop` / `_run_tool` / `_run_tool_loop` / `_run_workflow` / `_run_agent` / `_run_directive` / `_maybe_run_init_brief_or_block` / `_run_init_brief_command` / `_run_init_command`
> - `EngineSession.engine: Engine` 替代旧 `EngineSession.deps: EngineDeps`,`__post_init__` 一次性构造
>
> **`EngineDeps` 当前形态**(2026-07-13 实测):9 字段 + 5 rebind 方法 + 2 普通方法。`tool_loop` / `prose_client` / `review_llm` / `settings` 均存在;`story_agent` 字段已删(`chg-remove-roles`)。
>
> **长任务编排**:2026-07-09 `real-writing-pipeline` PR2 把 `write_chapter` 从 sync stub 升级为 LangGraph 5 节点图;`review_chapter` 仍为占位 stub(PR3)。`workflow_pending` 不再是合法 `DoneReason`(`Done(workflow_completed)` 替代)。
>
> 本节"已落地的 Engine 层结构"(§5) 描述的是 2026-07-08 形态;2026-07-13 起 `src/writer/engine/` 多出 `engine.py` 主类文件;`EngineDeps` 字段已扩展到 9 个;其余概念(ReAct / Plan-and-Execute / Tool-Use / Markdown directive)仍生效。

## 问题

当下主流的 Agent 架构模式有哪些?本项目为什么选择目前的形态?在不同抽象层之间如何保持职责清晰?

## 业务背景

Writer Agent 面向中文长篇小说的连续创作。用户的一次输入可能是确定命令,也可能是自然语言;落地的执行可能是秒级的伏笔查询,也可能是分钟级的章节写作。如果只用一种 Agent 范式,要么反应不够"轻",要么长任务不够"稳",两者会互相牵制。

文档 [15-LangChain前台调度Agent设计.md](./15-LangChain前台调度Agent设计.md) 与 [04-LangGraph多阶段编排与子代理隔离.md](./04-LangGraph多阶段编排与子代理隔离.md) 已经分别描述了前台与后台,本文从更宏观的视角对比常见 Agent 架构模式,回答本项目为什么采用"前台调度路由器 + 后台 LangGraph 工作流 + 角色化节点 + 业务 Tool + Markdown SKILL.md directives"这种混合形态。

## 技术难点

- 不同范式适合不同任务粒度,但是一个 Agent 实例很难同时兼容"毫秒级分发"与"分钟级长跑"
- 长任务如果交给单一 LLM Agent 自己决策循环,会出现调试困难、状态不可恢复、上下文无限增长
- 多 Agent 协同如果不约束共享状态,容易出现角色越权、重复劳动和 token 浪费

## 解决方案总览:分层而不是单 Agent

本项目并不追求"一个万能 Agent"。它把工作切成四层,每层选择最适合的范式:

| 层级 | 主要范式 | 职责 | 典型组件 |
| --- | --- | --- | --- |
| 前台调度层 | 结构化输出 + 规则版 + LLM fallback | 把用户输入转成 `AgentAction` | `IntentRouter` Protocol + `RuleBasedIntentRouter`(MVP)+ `LlmIntentRouter`(LangChain structured output)+ `CompositeRouter`(rule-first + LLM fallback) |
| 引擎层 | `match` dispatch + AsyncGenerator | 调度 `AgentAction` 到对应分支,产出事件流 | `writer.engine.loop.run_engine` + `EngineDeps` |
| 工作流 / 工具 / directive 层 | LangGraph(占位 workflow) + Tool-use + Markdown directive | 长任务、文件 IO、业务规则 | `_DefaultEngineDeps.run_workflow` + `ToolRegistry` + `DirectiveRegistry` |
| LLM Provider | LangChain `BaseChatModel` + structured output | 真正调 model | `writer.llm` + `ReActAgent` |

下文先介绍常见 Agent 架构,再解释为什么这种分层组合最适合本项目。

## 常见 Agent 架构模式

### 1. ReAct(Reason + Act)

Yao 等人 2022 年提出。核心循环是 `Thought → Action → Observation → Thought ...`。LLM 在每一轮先"思考"为什么做、调用什么工具,观察工具结果后再决定下一步。

优点:

- 实现简单,适合短链路决策
- 自然语言思考过程留下可读轨迹,便于调试

缺点:

- 没有显式全局计划,容易走弯路、重复调用、重读上下文
- 长任务容易"上下文爆炸"
- 不擅长需要并行或条件分支的工作

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

- 计划显式可见,便于人工审阅和缓存
- 中途执行出错时,可以只修复某一步而不是重跑全部
- 适合多步、有依赖的长任务

缺点:

- 计划本身可能错误或粒度不当,需要质量控制
- 对计划生成质量依赖较强

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

Shinn 等人 2023 年提出。在 ReAct 之外增加一个"反思"环节,把每轮结果写回长期记忆,下次执行时参考。适合需要多轮迭代、提升成功率的 Agent。

适合用在:审核-回流的循环节点上,例如本项目的 `review_gate` 决定是否回流到 `write_chapter`。

### 5. Multi-Agent / 角色协作

多个 Agent 实例按角色协同,常见结构:

- 对等通信(每个 Agent 能直接给其他 Agent 发消息)
- 总线式共享消息队列(AutoGen 风格)
- 监督者 / 主管(Supervisor / Hierarchical Agent)统一分发任务

适合:角色边界清晰、任务可分解、彼此可以并行处理的场景。

风险:共享可变状态、上下文不可控、token 浪费、调试困难。

### 6. Supervisor / Hierarchical Agent

上层有一个 Supervisor Agent 决定任务分发给哪个 Worker;Worker 完成后把结果汇报给 Supervisor,Supervisor 再决定下一步。LangGraph 的 `Supervisor` 模板就是这种思路。

适合:任务类型多、需要动态路由的场景。

### 7. Graph / State Machine Agent

把 Agent 的流转表达为一张图,节点是 LLM 调用或 Tool 调用,边是条件路由。LangGraph 是典型代表。可以组合上述各种范式作为节点行为。

优点:

- 流程可见、可测试、可持久化、可恢复
- 自然支持条件分支、并行、回流
- 与业务状态机贴合

缺点:

- 抽象成本高,小任务过度设计

### 8. Tool-Use(工具调用)与 RAG Agent

Tool-Use 本身不是 Agent 范式,但是大多数 Agent 都依赖它。RAG Agent 把外部检索结果作为上下文片段输入给 LLM。

适合:本项目的伏笔检索、关键词 grep、章节定位都依赖这条线。**注意:RAG 已经被 chg-remove-rag 删除(2026-07-08),改用结构化 ledger + project grep 替代**(详见 [备忘 12](./12-RAG与检索实现方案.md))。

## 本项目采用的混合架构

综上所述,本项目**没有押注单一范式**,而是按任务粒度组合:

- **前台**:`CompositeRouter(primary=RuleBasedIntentRouter, fallback=LlmIntentRouter)`
  - 主范式:Plan-and-Execute 的退化版 + 结构化输出
  - 高频命令纯规则,自然语言走 LLM,LLM flaky 自动回退
  - 只产出 `AgentAction`,不直接动手
- **引擎**:`writer.engine.loop.run_engine` AsyncGenerator + `match action.action_type`
  - 主范式:事件流 dispatch(单层 match,顶层 try/except)
  - `run_command` 命中 directive 时走 `_run_directive()` 把 SKILL.md body + references 喂给 LLM 工具循环
  - `call_tool` 走 `_run_tool`(rule-only)/ `_run_tool_loop`(LLM 多步)
  - `start_workflow` 走 `_DefaultEngineDeps.run_workflow`(占位,等真实 LangGraph 图)
- **工具层**:6 个 builtin Tool(`safe_read_file` / `safe_list_dir` / `project_search` / `foreshadow_search` / `chapter_locate` / `wordcount`)
  - 主范式:Tool-Use + LangChain `bind_tools` / JSON-prompt 双 provider
  - 业务级"做什么"由 **Markdown SKILL.md directives** 表达(2 个 shipped:`/大纲` `/目录`),不是 Python 类
- **角色层(题材分支)**:每个题材一个 Markdown agent(`writer/agents/_shipped/*.md` 4 份,2026-07-09 `chg-remove-roles` 后取代原 `StoryAgent` Python 类)
  - `other` / `历史` / `言情` / `玄幻`(兜底)
  - 通过 `writer.agents.AgentRegistry` 按 `AGENT.md` `题材:` 行动态派生(LLM dispatch 时按 agent `description` 自选)
  - 每个 agent 的 `chapters` 字符串前缀约定表达题材差异(在 directive body 内 inline,不再由 Python 端注入)

这五个层级分别对应不同的范式,但共同遵循几个原则:

1. **不把长任务交给前台路由器。** `start_workflow` 一旦返回,前台就不再干涉,由 LangGraph 接管。
2. **不引入独立的多 Agent 实例通信。** 多个角色通过 LangGraph 节点的 prompt 模板切换,而不是各自拥有独立进程;它们看到的上下文由 `_build_canon_block` 裁剪。
3. **状态机只作展示。** `ProjectState` 是 S0-S5 大状态标签,服务 `/状态` 显示;命令拦截机制(`validate_command_available`)已随 `chg-remove-state-machine-enforcement` 删除,不再拦截任何指令。
4. **Tool 是 Agent 的边界。** 任何文件副作用必须经过注册过的 Tool,避免 LLM 直接编辑 Markdown。
5. **业务规则是 directive。** "写大纲怎么做"、"续写章节怎么做"等业务规则通过 SKILL.md markdown 文件描述,LLM 在工具循环里直接消费这些指令。

## 设计思路对照

| 项目要求 | 单 Agent 范式难以满足的原因 | 本项目做法 |
| --- | --- | --- |
| 高频命令毫秒级响应 | 单一 ReAct 每次都要把历史塞满 prompt | 前台调度路由器只关心命令路由,工作流交给后台 |
| 长章节写作分钟级稳定 | ReAct 容易走偏,token 越长越慢 | 走 LangGraph 显式计划与节点;LLM 工具循环有 `MAX_LOOP_STEPS=5` 上限 |
| 角色不能越权 | 多 Agent 共享消息总线容易泄露上下文 | 每个节点只读自己需要的 canon block 子集 |
| 审核失败要回流 | 单 Agent 没有显式回流边 | `review_gate` 通过条件边回 `write_chapter` |
| 状态可恢复 | ReAct 历史不可序列化检查点 | EngineSession 维护 turn history,WorkflowStub 占位等 LangGraph checkpoint |
| 历史题材可选加载 | ReAct 不知道是否加载历史顾问 | 通过 `project_genre` 字段 + `writer.agents.AgentRegistry` 按题材派生 Markdown agent;LLM 按 `description` 自选(`chg-remove-roles`,2026-07-09) |
| 项目级定制业务规则 | Python 类难覆盖 | 项目目录 `.writer/skills/` 里放 `.md` 即可覆盖 shipped SKILL.md |

## 最小 demo / 伪代码

下面给出一个把四种范式组合在一起的端到端最小骨架:

```python
from typing import Literal
from langchain_core.prompts import ChatPromptTemplate
from langchain_core.tools import tool
from langgraph.graph import END, StateGraph
from langgraph.prebuilt import ToolNode
from pydantic import BaseModel


# ---------- 1. 前台:结构化输出路由器 ----------
ActionType = Literal["start_workflow", "call_tool", "ask_user", "answer_directly"]


class AgentAction(BaseModel):
    model_config = {"frozen": True}
    action_type: ActionType
    workflow: str | None = None
    tool_name: str | None = None
    arguments: dict = {}
    answer: str | None = None


def build_router(llm):
    return COMMAND_AGENT_PROMPT | llm.with_structured_output(AgentAction)


# ---------- 2. 引擎:事件流 dispatch ----------
async def dispatch(action: AgentAction, deps):
    match action.action_type:
        case "answer_directly":
            yield Done(reason="answered", payload={"answer": action.answer})
        case "call_tool":
            async for event in deps.tool_loop.run(action, ctx, deps, cfg):
                yield event
        case "start_workflow":
            for chunk in deps.run_workflow(action.workflow or "", ctx):
                yield TextChunk(text=chunk)
            yield Done(reason="workflow_pending")


# ---------- 3. 业务 Tool 层 ----------
@tool
def safe_read_file(runtime, *, path: str) -> str:
    target = runtime.safe_path(path)
    return target.read_text(encoding="utf-8")[:runtime.max_file_size]


tool_node = ToolNode([safe_read_file])


# ---------- 4. Markdown directive ----------
# `<project_root>/.writer/skills/大纲/SKILL.md`:
# ---
# command: /大纲
# description: 生成大纲并写入 outline/大纲.md
# ---
# 你是一位编剧顾问。读取 `创意/核心创意.md` 与 `大纲/` 目录,
# 然后调用 safe_write_file 写 outline/大纲.md ...
```

可以看到:

- 前台 `IntentRouter` 是 **Plan-and-Route + 结构化输出**(协议,实现可换);
- 后台引擎是 **事件流 dispatch**,内嵌 `tool_loop.run` 实现的 **ReAct 多步**;
- 节点内允许嵌套一次小的 ReAct(LLM 工具循环);
- 业务 Tool 由 `ToolRegistry` 统一封装,Markdown directive 由 `DirectiveRegistry` 派生。

## 与已有文档的关系

- 与 [04-LangGraph多阶段编排与子代理隔离.md](./04-LangGraph多阶段编排与子代理隔离.md) 互为补充:本文讲"为什么选这种范式",该文讲"怎么搭图"
- 与 [15-LangChain前台调度Agent设计.md](./15-LangChain前台调度Agent设计.md) 互为补充:本文把前台路由器放回整个架构对比中,该文给出具体实现
- 与 [13-核心Tool设计.md](./13-核心Tool设计.md) 互为补充:本文讲 Tool-Use 在整体 Agent 中的位置,该文给出 builtin Tool 清单与安全约束
- 与 [01-项目状态机与命令可用性.md](./01-项目状态机与命令可用性.md) 互为补充:`ProjectState` 是 Agent 行动的先决条件,任何 Agent 操作都必须先经过状态校验

## 落地建议

- 不要尝试用一个 LangChain Agent 完成所有任务。命令分发交给前台路由器,写作交给 LangGraph,文件副作用交给 Tool。
- 不要让多角色变成多进程。角色之间的差异由 prompt 区分,上下文通过 `_build_canon_block` 裁剪,而非共享可变内存。
- 引入新范式前先问:它解决的是哪一层的痛点?是前台路由、长任务编排、还是反思回流?混用要明确边界。
- 把每种范式的特征(思考轨迹、计划、反思)落盘:计划写到 `大纲/`,反思历史写到 `修订/`,便于后续训练或调试。
- MVP 阶段保留规则版 `route()` 作为 primary(配合 `CompositeRouter` 包装 LLM fallback),避免 LLM 把 `/大纲` 误识别为说明性问题。

## 已落地的 Engine 层结构(2026-07-08)

备忘 16 给出的是 4 层概念模型。本节把"前台调度层 + 后台引擎层"具体落到 `writer.engine` 包的代码形态。

### 5 文件布局

```
writer/engine/
├── __init__.py    # 公共门面: 只 re-export, 不放逻辑
├── events.py      # Event 数据类层级(frozen=True, 单一基类)
├── context.py     # EngineContext(frozen) — 单一输入契约
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

### EngineDeps 当前形态(2026-07-08 实测)

```python
@runtime_checkable
class EngineDeps(Protocol):
    # 字段
    router: IntentRouter
    agent_registry: AgentRegistry                # 2026-07-09 chg-remove-roles:story_agent 字段删除
    tool_registry: ToolRegistry
    tool_runtime: ToolRuntime
    directive_registry: DirectiveRegistry       # NEW 2026-07-09 (原 skill_registry)
    tool_loop: ReActAgent | None                # NEW 2026-07-08 (ReAct 多步)

    # 方法
    def route(self, user_input, project_state) -> AgentAction: ...
    def run_workflow(self, name, ctx) -> Iterable[str]: ...
    def rebind_tool_runtime(self, new_runtime) -> EngineDeps: ...
    def rebind_skill_registry(self, new_registry) -> EngineDeps: ...  # back-compat alias
    def rebind_directive_registry(self, new_registry) -> EngineDeps: ...
    def rebind_agent_registry(self, new_registry) -> AgentRegistry: ...  # 2026-07-09 fea-agent-mirror
```

`production_deps()` 默认装配(纯工厂,2026-07-08 M2 起;`chg-remove-roles` 2026-07-09 后去掉 `story_agent=` / `genre=` kwarg):

- `router`:有 API key 时返回 `CompositeRouter`,否则纯 `RuleBasedIntentRouter`
- `agent_registry`:`writer.agents.built_agent_registry(project_root=...)` — 题材分支由 `_shipped/*.md` 4 份 Markdown 携带(`chg-remove-roles`,2026-07-09)
- `tool_registry`:`built_tool_registry()` 9 个 builtin Tool(`safe_write_file` / `safe_edit_file` / `safe_glob` 由 `chg-add-write-edit-glob` 补入)
- `tool_runtime`:`ToolRuntime(project_root=...)`,S0 路径下用 sentinel `/__no_project__`
- `directive_registry`:`built_directive_registry(project_root=...)`,项目级 SKILL.md 通过 last-write-wins 覆盖 shipped
- `tool_loop`:有 API key 时构造 `ReActAgent`(否则 `None`,引擎走同步 `_run_tool`)

### EngineDeps 的扩展点

按需扩展(目前**未**实现的扩展点):

- `workflow_starter`:richer async workflow entrypoint(per 备忘 04,目前是 sync `run_workflow`)
- `interrupt_handler`:InterruptHandler(per 备忘 14,目前是 engine 直接 yield Interrupt 事件)
- `stop_hooks`:StopHookRegistry(参考 Claude Code §12.3)

新增能力只能通过 `EngineDeps` 扩展,不直接改 `loop.py`。

### Engine 是无状态 AsyncGenerator

`run_engine(ctx, deps, *, config)` 返回 `AsyncIterator[Event]`,本身不持有任何会话状态。原因:

1. **流式消费友好**: REPL `async for event` 逐事件渲染,token-level 流式输出可直接接。
2. **取消成本低**: REPL Ctrl+C 可以中断 async iteration,engine 不持有需要清理的资源。
3. **session 可任意 restart**: 重连 session 不需要重置 engine 内存,只需重新调用 `run_engine`。
4. **易测**: 单个 turn = 单次 AsyncGenerator 消费,test 直接 `async for` 就行。

会话级状态(`EngineSession` 的 turn history / pending_interrupt / project_root 切换 / deps 热替换)属于 `writer.session`,不在 engine 内部。

### 与 Layer 表的对应

回头看 4 层模型,Engine 实际上跨越前台 + 后台两层:

- **前台调度层** → `engine.loop` 调 `deps.route()`,发 `ActionEvent` 后再分派
- **后台工作流层** → engine 内 `start_workflow` 分支占位 `Done(reason="workflow_pending")`,等真实 LangGraph 落地时把这个分支换成 `WorkflowStarter.start(workflow, ctx)`
- **业务工具层** → `call_tool` 分支走 `_run_tool`(同步)/ `_run_tool_loop`(LLM 多步)
- **directive 层** → `run_command` 命中 directive_registry 时走 `_run_directive()`,body + references 喂给 LLM 工具循环
- **记忆层** → 现在是 `_build_canon_block` 纯文件拼装 + `foreshadow_search` ledger 查询,**不**在 engine 内部

## 更新后的验收标准

在原本六条之外,补充:

- Engine 包严格 5 文件布局,新增能力(workflow / tool / interrupt / directive)只通过 `EngineDeps` 扩展,不直接改 `loop.py`
- `EngineContext / EngineConfig / Event 子类 / AgentAction` 全程 frozen(`@dataclass(frozen=True)` 或 Pydantic `model_config={"frozen": True}`)
- `run_engine` 是 `AsyncIterator[Event]`,不持有会话状态
- `EngineDeps` 必须 `@runtime_checkable`,便于测试时 mock
- 6 字段 + 4 方法全部需要在手写 `EngineDeps` stub 时实现(测试 fakes 经常漏 `tool_loop = None` 字段);`chg-remove-roles`(2026-07-09)后 `rebind_story_agent` 不再存在
- LLM 工具循环有 `MAX_LOOP_STEPS=5` 上限,耗尽时走 `Done(tool_loop_completed, payload={tool_calls_made, last_output})`,**不算** aborted
- `ToolError` / `SkillError` 在 engine 边界 catch 后产出 `ErrorEvent + Done(aborted)`,不外溢
- `rebind_*` 系列方法是热替换 deps 的唯一接口;任何 duck-typed mutation 已被禁止(2026-07-05 M6 修复)

## 验收标准

- 前台路由器输出一律是 `AgentAction`,不允许自由文本
- 长任务只能由后台 LangGraph 执行,前台不直接推进 draft
- 任何文件写入都通过 builtin Tool(`safe_read_file` / `safe_write_file` 间接),不能由 LLM 直接编辑 Markdown
- 题材分支只影响 `writer.agents.AgentRegistry`(4 份 `_shipped/*.md`),不影响 `IntentRouter` / `ToolRegistry` / `directive_registry`(2026-07-09 `chg-remove-roles` 后)
- 审核结果可以决定是否回流到 `write` 节点,回流次数受 `retry_count` 上限保护
- 在事件流中能清晰看到每个范式的位置:Plan(`run_command` 命中 directive → LLM 工具循环)、Execute(`call_tool` / `start_workflow`)、Review(`run_workflow` 内 review_gate)

## 其他常见范式速查

- **BabyAGI / AutoGPT**:自主任务分解 + 循环执行,适合开放式探索,但可控性差,不适合本项目
- **Toolformer 思路**:让模型在训练时学会何时调用工具,本项目不需要重新训练模型,所以用 prompt 引导 + Tool 列表约束
- **Voyager 风格技能树**:运行中学到的技能写回工具库。本项目已经走 SKILL.md 路线:**成功的写作技巧沉淀为 `.writer/skills/<cmd>/SKILL.md`**,LLM 工具循环直接消费
- **RAG-Fusion / HyDE**:检索时多查询融合或假想文档检索——本项目 RAG 已删除(`chg-remove-rag`),这条线不再适用