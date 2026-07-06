# LangChain 前台调度 Agent 设计

## 问题

本项目是否应该提供一个 LangChain Agent,用来接收用户输入并进行角色选择?应该如何设计该 Agent?

## 业务背景

用户在 REPL 中不一定总是输入严格命令。有时会输入“帮我继续写下一章”“这个主角人设太弱了,改一下”“查一下 F003 伏笔”。系统需要理解用户意图,选择合适角色或工作流。

## 技术难点

如果做一个万能 Agent 直接写文件、调用 LLM 写整章、推进状态机,系统会难以调试和恢复。长任务应该交给 LangGraph,文件写入应该交给 Tool,命令可用性应该由状态机判断。LangChain Agent 更适合做前台调度,而不是承担全部业务。

## 解决方案

提供 `IntentRouter` 作为前台路由层。它只负责把用户输入转成结构化 `AgentAction`,协议由 `writer.routing.IntentRouter` 给出,当前 MVP 实现是 `RuleBasedIntentRouter`(无网络),未来由 `LlmIntentRouter`(LangChain structured output)接在同协议后面:

- `run_command`:执行明确命令。
- `call_tool`:调用轻量工具。
- `start_workflow`:启动 LangGraph 长任务。
- `ask_user`:请求用户补充信息。
- `answer_directly`:直接回答说明性问题。

角色选择也在这里完成,但角色只作为后续 workflow 或 prompt 的参数,不由该 Agent 自己执行全部流程。

## 最小化代码

```python
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field


Role = Literal["story_consultant", "proofreader", "historian", "reviewer"]
ActionType = Literal["run_command", "call_tool", "start_workflow", "ask_user", "answer_directly"]


class AgentAction(BaseModel):
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


class RuleBasedIntentRouter:
    def route(self, user_input: str, project_state: str) -> AgentAction:
        text = user_input.strip()

        if text.startswith("/创作"):
            return AgentAction(
                action_type="start_workflow",
                command="/创作",
                role="story_consultant",
                workflow="write_chapter",
                arguments={"raw": text},
            )

        if text.startswith("/审核"):
            return AgentAction(
                action_type="start_workflow",
                command="/审核",
                role="reviewer",
                workflow="review_chapter",
                arguments={"raw": text},
            )

        if "伏笔" in text:
            return AgentAction(
                action_type="call_tool",
                role="story_consultant",
                tool_name="foreshadow_query",
                arguments={"query": text},
            )

        return AgentAction(
            action_type="answer_directly",
            answer="我可以处理 /init、/大纲、/目录、/创作、/审核、/改 等写作命令。",
        )
```

> 当前实现以 `/创作` 作为写章节工作流入口；早期文档中的 `/写作` 可视为旧命名,除非后续显式增加别名,不要在 router / 状态机示例里继续使用。

## 核心依赖版 LangChain Agent 代码

第一阶段可以用规则版 `route()`(`RuleBasedIntentRouter`)保证稳定。第二阶段再接 LangChain 的结构化输出,作为 `LlmIntentRouter(IntentRouter)` 实现 `route()`:

```python
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI


COMMAND_AGENT_PROMPT = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            """
你是 Writer Agent 的前台调度 Agent。
你的职责是把用户输入转成 AgentAction。

边界:
- 不直接写文件。
- 不直接生成整章正文。
- 不直接修改 AGENT.md。
- 长任务必须返回 start_workflow。
- 轻量查询可以返回 call_tool。
- 信息不足时返回 ask_user。
""",
        ),
        (
            "human",
            """
项目状态:{project_state}
用户输入:{user_input}
""",
        ),
    ]
)


def build_intent_router() -> object:
    """Factory for the future ``LlmIntentRouter`` (LangChain structured output)."""
    llm = ChatOpenAI(
        model="deepseek-v3",
        temperature=0,
        base_url="https://api.example.com/v1",
        api_key="YOUR_API_KEY",
    )
    structured_llm = llm.with_structured_output(AgentAction)
    return COMMAND_AGENT_PROMPT | structured_llm


def route_with_langchain(user_input: str, project_state: str) -> AgentAction:
    """Future-stage helper: thin wrapper over the LangChain structured-output chain."""
    chain = build_intent_router()
    return chain.invoke(
        {
            "user_input": user_input,
            "project_state": project_state,
        }
    )
```

Prompt 要强调边界:

- 不直接写文件。
- 不直接推进 `AGENT.md` 状态。
- 长任务必须返回 `start_workflow`。
- 需要用户输入时返回 `ask_user`。
- 能用确定性解析时不要臆测。

## 推荐运行链路

```text
用户输入
  ↓
IntentRouter.route() 输出 AgentAction
  ↓
会话控制层校验项目状态
  ↓
Command / Tool / LangGraph workflow / Interrupt
  ↓
REPL 渲染结果或继续等待用户
```

## 落地建议

- MVP 先用规则解析高频命令,避免 LLM 把命令理解错。
- 自然语言输入再交给 LangChain Agent 做结构化意图识别。
- Agent 输出必须是 Pydantic 结构,不要让下游解析自由文本。
- 状态机校验放在 Agent 之后,防止模型绕过命令状态约束。

## 验收标准

- “帮我写下一章”能转成 `start_workflow/write_chapter`。
- “查一下 F003”能转成 `call_tool/foreshadow_query`。
- “这个项目怎么用”能直接回答,不启动长任务。
- LangChain Agent 不能绕过状态机直接写文件。
