# LLM 用户交互与 REPL 中断协议

## 问题

如果 LLM 需要与用户交互,比如需要用户进行选择或输入文本,REPL 如何实现?

## 业务背景

写作流程中经常需要用户介入。例如已有大纲时选择重写或续写,历史题材边界需要用户确认,生成多个主角设定后需要用户选择。

## 技术难点

不能让 LLM 直接控制终端输入,否则流程不可恢复、不可测试,也不利于未来接 Web UI。用户交互必须被表示成结构化事件,由 REPL 统一渲染和收集结果。

## 解决方案

引入 `AgentInterrupt` 协议。LangGraph 节点或 Tool 遇到需要用户决策时,不直接 `input()`,而是返回或抛出结构化 interrupt:

- `choice`:让用户从选项中选择。
- `text`:让用户输入单行或多行文本。
- `confirm`:让用户确认破坏性操作。

REPL 收到 interrupt 后暂停当前 run,展示交互界面,把用户回答写回 state,然后 resume。

## 最小化代码

```python
from dataclasses import dataclass
from typing import Literal


@dataclass
class AgentInterrupt:
    type: Literal["choice", "text", "confirm"]
    prompt: str
    options: list[str] | None = None
    default: str | bool | None = None
    multiline: bool = False


@dataclass
class UserReply:
    value: str | bool


def ask_user_choice(prompt: str, options: list[str], default: str | None = None) -> AgentInterrupt:
    return AgentInterrupt(
        type="choice",
        prompt=prompt,
        options=options,
        default=default,
    )


def repl_handle_interrupt(interrupt: AgentInterrupt) -> UserReply:
    if interrupt.type == "choice":
        print(interrupt.prompt)
        for index, option in enumerate(interrupt.options or [], start=1):
            print(f"{index}. {option}")
        raw = input("> ").strip()
        selected = (interrupt.options or [])[int(raw) - 1]
        return UserReply(value=selected)

    if interrupt.type == "text":
        if interrupt.multiline:
            lines: list[str] = []
            while True:
                line = input()
                if line == '"""':
                    break
                lines.append(line)
            return UserReply(value="\n".join(lines))
        return UserReply(value=input(f"{interrupt.prompt}\n> "))

    if interrupt.type == "confirm":
        raw = input(f"{interrupt.prompt} [y/N] ").strip().lower()
        return UserReply(value=raw == "y")

    raise ValueError(f"未知 interrupt 类型: {interrupt.type}")
```

## LangGraph 节点伪代码

```python
def outline_node(state: dict) -> dict:
    if outline_exists(state["project_root"]):
        return {
            "interrupt": ask_user_choice(
                prompt="大纲已存在,请选择处理方式",
                options=["查看当前大纲", "续写", "覆盖重写", "取消"],
                default="查看当前大纲",
            )
        }

    return {"next": "generate_outline"}


def resume_after_user_reply(state: dict, reply: UserReply) -> dict:
    state["user_reply"] = reply.value
    return state
```

## 核心依赖版最小代码

```python
from typing import TypedDict

from langgraph.graph import END, StateGraph
from langgraph.types import Command, interrupt
from prompt_toolkit import PromptSession
from rich.console import Console


class ReplState(TypedDict):
    user_input: str
    outline_mode: str


def ask_outline_mode(state: ReplState) -> Command:
    answer = interrupt(
        {
            "type": "choice",
            "prompt": "大纲已存在,请选择处理方式",
            "options": ["查看当前大纲", "续写", "覆盖重写", "取消"],
        }
    )
    return Command(update={"outline_mode": answer}, goto=END)


graph = StateGraph(ReplState)
graph.add_node("ask_outline_mode", ask_outline_mode)
graph.set_entry_point("ask_outline_mode")
compiled_graph = graph.compile()


def repl_loop() -> None:
    console = Console()
    session = PromptSession()
    user_input = session.prompt("writer> ")
    result = compiled_graph.invoke({"user_input": user_input, "outline_mode": ""})
    console.print(result)
```

## 落地建议

- 第一版可自定义 interrupt 协议,后续再映射到 LangGraph 原生 interrupt/resume 能力。
- 所有用户交互都进入 checkpoint,避免中断后丢失上下文。
- REPL 渲染层只认识 `AgentInterrupt`,不关心是哪一个 Agent 节点发起。
- Web UI 未来可以复用同一个协议。

## 验收标准

- LLM 或节点需要用户选择时,不会直接阻塞在底层 `input()`。
- Ctrl+C 后重启,能恢复到等待用户选择的状态。
- 选择、文本、确认三类交互都能被测试覆盖。
- `/大纲 rewrite`、`/reset` 等破坏性操作必须走确认协议。
