# 前台调度 IntentRouter 设计

> **2026-07-05 重要修订**:本文档原标题《LangChain 前台调度 Agent 设计》描述的是单一 `IntentRouter` + `RuleBasedIntentRouter` MVP 的设计;该 MVP 已经落地,但 `LlmIntentRouter` + `CompositeRouter` 也已在 [arch-optimizer M5/M6](../../tmp/architecture-reports/) 修复后实装(`src/writer/routing/`),不再是"未来阶段"。
>
> 本文以**当前形态**重写:`IntentRouter` Protocol + `RuleBasedIntentRouter`(MVP)+ `LlmIntentRouter`(LangChain structured output)+ `CompositeRouter`(rule-first + LLM fallback)。LangChain 的角色是"在 LLM 路由器里调用 `with_structured_output` 翻译自然语言",不再负责 Agent 状态机。

## 问题

用户在 REPL 中不一定总是输入严格命令。有时是"帮我继续写下一章""这个主角人设太弱了,改一下""查一下 F003 伏笔"。系统需要理解用户意图,选择合适角色或工作流。

## 业务背景

REPL 用户输入混合三类:

1. **明确命令**(以 `/` 开头):路由 + 命令矩阵校验后 dispatch
2. **自然语言意图**(无 `/`):LLM 结构化输出转 `AgentAction`
3. **框架命令**(`/退出` `/帮助` `/状态`):REPL 自身拦截,不进 engine

## 技术难点

如果做一个万能 Agent 直接写文件、调用 LLM 写整章、推进状态机,系统会难以调试和恢复:

- 长任务应该交给 LangGraph(占位 workflow 现在是 `_DefaultEngineDeps.run_workflow`,真实图待 `EngineDeps` 注入 `WorkflowStarter`)
- 文件写入应该交给 Tool(`safe_read_file` / `safe_write_file`)
- 命令可用性应该由状态机判断(`writer.project.validate_command_available`)

前台调度的边界:**只产出 `AgentAction`,不直接动手**。

## 解决方案

`IntentRouter` 是前台路由层,**协议** 由 `writer.routing.IntentRouter` 给出,**实现** 三个并存:

| 实现 | 何时用 | 网络依赖 |
| --- | --- | --- |
| `RuleBasedIntentRouter` | 默认;高频命令毫秒级响应 | 无 |
| `LlmIntentRouter` | 自然语言输入;LLM 翻译为结构化 action | 需要 API key |
| `CompositeRouter` | 生产默认(rule-first + LLM fallback) | 需要 API key,但 flaky 时回退 |

`AgentAction` 是路由输出,5 种 `action_type`:

- `run_command` — 执行明确命令(`/init`、`/大纲` 等)
- `call_tool` — 调用轻量工具(`/字数统计`、自然语言含"伏笔")
- `start_workflow` — 启动 LangGraph 长任务(`/创作`、`/审核`)
- `ask_user` — 请求用户补充信息
- `answer_directly` — 直接回答说明性问题

角色选择也在路由结果里(`role: story_agent | proofreader | historian | reviewer`),但角色只作为后续 workflow 或 prompt 的参数,不由路由器自己执行全部流程。

## 最小化代码

```python
from typing import Literal, Protocol, runtime_checkable
from pydantic import BaseModel, Field


Role = Literal["story_agent", "proofreader", "historian", "reviewer"]
ActionType = Literal["run_command", "call_tool", "start_workflow", "ask_user", "answer_directly"]


class AgentAction(BaseModel):
    """路由输出,frozen(BaseModel + model_config={"frozen": True})。"""

    model_config = {"frozen": True}
    action_type: ActionType
    command: str | None = None
    role: Role | None = None
    workflow: str | None = None
    tool_name: str | None = None
    arguments: dict = Field(default_factory=dict)
    answer: str | None = None
    user_prompt: str | None = None


@runtime_checkable
class IntentRouter(Protocol):
    def route(self, user_input: str, project_state: str) -> AgentAction: ...
```

```python
# MVP 规则版(`src/writer/routing/intent_router.py`)
class RuleBasedIntentRouter:
    _FRAMEWORK_KEYWORDS: frozenset[str] = frozenset({"init", "状态", "退出", "帮助"})

    def route(self, user_input, project_state):
        text = user_input.strip()
        if text.startswith("/字数统计"):
            return AgentAction(action_type="call_tool", command="/字数统计",
                               tool_name="wordcount",
                               arguments={"path": _command_argument(text, "/字数统计") or "."})
        if text.startswith("/创作"):
            return AgentAction(action_type="start_workflow", command="/创作",
                               workflow="write_chapter", arguments={"raw": text})
        if text.startswith("/审核"):
            return AgentAction(action_type="start_workflow", command="/审核",
                               workflow="review_chapter", arguments={"raw": text})
        if "伏笔" in text or "F0" in text:
            return AgentAction(action_type="call_tool", tool_name="foreshadow_search",
                               arguments=_parse_foreshadow_args(text))
        if text.startswith("/"):
            return AgentAction(action_type="run_command",
                               command=text.split(maxsplit=1)[0])
        return AgentAction(action_type="answer_directly",
                           answer=f"我可以处理 /init、/大纲、/目录、/创作、/审核 等写作命令。你刚才说的是:{text}")

    @classmethod
    def looks_like_command(cls, text: str) -> bool:
        stripped = text.strip()
        if not stripped:
            return False
        if stripped.startswith("/"):
            return True
        return stripped in cls._FRAMEWORK_KEYWORDS
```

> 当前实现以 `/创作` 作为写章节工作流入口;早期文档中的 `/写作` 可视为旧命名,除非后续显式增加别名,不要在 router / 状态机示例里继续使用。

## 核心依赖版 LangChain Router 代码

`LlmIntentRouter` 在 `src/writer/routing/llm_router.py` 实装,有两条 provider 路径(per `needs_json_prompt_structured_output`):

1. **native `bind_tools` / `with_structured_output`**:OpenAI 兼容协议(走 deepseek-v3 / GPT 等)
2. **JSON-prompt**:某些 model 不支持原生 structured output,把 Pydantic schema 渲染进 prompt,要求模型输出 JSON

```python
class LlmIntentRouter(IntentRouter):
    def __init__(self, settings, *, llm=None, chain=None):
        self._chain = None
        self._llm = None
        self._use_json_prompt = False
        if chain is not None:
            self._chain = chain
            return
        if llm is None:
            llm = get_llm(settings)
        if needs_json_prompt_structured_output(settings):
            self._llm = llm
            self._use_json_prompt = True
            return
        structured_llm = llm.with_structured_output(AgentAction)
        self._chain = COMMAND_AGENT_PROMPT | structured_llm

    def route(self, user_input, project_state):
        if self._use_json_prompt:
            messages = COMMAND_AGENT_PROMPT.invoke(
                {"user_input": user_input, "project_state": project_state}
            ).to_messages()
            return _normalize_action(
                invoke_structured_json(self._llm, messages, AgentAction)
            )
        result = self._chain.invoke({"user_input": user_input, "project_state": project_state})
        if isinstance(result, AgentAction):
            return _normalize_action(result)
        return _normalize_action(AgentAction.model_validate(result))
```

`_normalize_action()` 补充 LLM 经常漏填的确定性字段(`command` / `role`),保证 engine 边界契约稳定。

`CompositeRouter` 把两个路由器粘起来(rule-first + LLM fallback):

```python
class CompositeRouter(IntentRouter):
    def __init__(self, primary: IntentRouter, fallback: IntentRouter):
        self._primary = primary
        self._fallback = fallback

    def route(self, user_input, project_state):
        if RuleBasedIntentRouter.looks_like_command(user_input):
            return self._primary.route(user_input, project_state)
        try:
            return self._fallback.route(user_input, project_state)
        except Exception as exc:
            log.warning("LLM router 失败,回退到 rule router: %r", exc, exc_info=True)
            return self._primary.route(user_input, project_state)
```

`production_deps()` 默认装配 `CompositeRouter(primary=RuleBasedIntentRouter(), fallback=LlmIntentRouter(settings))`,仅在 `settings.has_api_key` 时启用 LLM fallback。

Prompt 模板位置:`src/writer/prompts/router.py::COMMAND_AGENT_TEMPLATE`,不在本备忘硬编码。Prompt 强调边界:

- 不直接写文件
- 不直接生成整章正文
- 不直接修改 `AGENT.md`
- 长任务必须返回 `start_workflow`
- 轻量查询可以返回 `call_tool`
- 信息不足时返回 `ask_user`

## 推荐运行链路

```text
用户输入
  ↓
CompositeRouter.route() → AgentAction
  ├─ 规则命中(以 / 开头 或框架关键词) → RuleBasedIntentRouter 立即返回
  └─ 自由文本 → LlmIntentRouter → structured AgentAction
  ↓
EngineDeps.route() 把 AgentAction 喂给 engine.loop 分派
  ↓
match action.action_type:
  - answer_directly → yield Done("answered")
  - run_command → 检查 directive_registry,落到 SKILL.md → LLM 工具循环
  - call_tool → 同步 _run_tool 或 LLM 工具循环
  - start_workflow → engine.deps.run_workflow(name, ctx)
  - ask_user → yield Interrupt → yield Done("ask_user")
```

## 落地建议

- 默认生产装配是 `CompositeRouter`,rule-first 保证高频命令稳定(零 LLM cost)
- 自然语言输入再走 LLM,且 fallback 在 LLM flaky 时自动接管
- 路由器输出必须是 Pydantic `AgentAction`(`model_config={"frozen": True}`),**不**让下游解析自由文本
- 状态机校验放在路由之后,防止模型绕过命令状态约束
- 不要尝试用一个 LangChain Agent 完成所有任务。命令分发交给前台路由器,长任务交给 LangGraph,文件副作用交给 Tool

## 验收标准

- `/大纲`、`/目录` 这类以 `/` 开头的命令,**不**触发 LLM 调用,纯规则即可路由到对应 SKILL.md directive
- 自然语言输入"帮我写下一章"应能转成 `start_workflow/write_chapter`
- "查一下 F003" 能转成 `call_tool/foreshadow_search(id="F003", keyword=...)`
- LLM flaky 时,`CompositeRouter.fallback` 抛异常后应能回退到 `RuleBasedIntentRouter` 的 `answer_directly`,不阻断 REPL
- 路由器**不**能绕过状态机直接写文件