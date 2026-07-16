# LLM 用户交互与 REPL 中断协议

## 问题

如果 LLM 需要与用户交互,比如需要用户进行选择或输入文本,REPL 如何实现?

## 业务背景

写作流程中经常需要用户介入。例如已有大纲时选择重写或续写,历史题材边界需要用户确认,生成多个主角设定后需要用户选择。

## 技术难点

不能让 LLM 直接控制终端输入,否则流程不可恢复、不可测试,也不利于未来接 Web UI。用户交互必须被表示成结构化事件,由 REPL 统一渲染和收集结果。

## 解决方案

引入 `Interrupt` 事件 dataclass(per `src/writer/engine/events.py::Interrupt`,2026-07-08 实测)。引擎或 LLM 工具循环遇到需要用户决策时,**不**直接 `input()`,而是 yield `Interrupt` 事件给 REPL:

- `choice`:让用户从选项中选择。
- `text`:让用户输入单行或多行文本。
- `confirm`:让用户确认破坏性操作。

REPL 收到 interrupt 后展示交互界面,把用户回答拼到下一次 turn 的 `user_input`(`[pending] {prompt}\n[answer] {user_input}` per `compose_pending_input`)再喂给引擎。本轮以 `Done(reason="ask_user")` 终结。

## 最小化代码

实际 `Interrupt`(`src/writer/engine/events.py`):

```python
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Interrupt(Event):
    """引擎发出的"等待用户回答"事件,frozen 子类。"""

    type: Literal["choice", "text", "confirm"]
    prompt: str
    options: list[str] | None = None
```

`Engine.compose_pending_input`(实际 `src/writer/session/engine.py`):

```python
def compose_pending_input(original: str, pending: Interrupt | None) -> str:
    if pending is None:
        return original
    return f"[pending] {pending.prompt}\n[answer] {original}"
```

引擎分支:

```python
case "ask_user":
    prompt = action.user_prompt or "请补充信息"
    yield Interrupt(type="text", prompt=prompt, options=None)
    yield Done(reason="ask_user", payload={"prompt": prompt})
```

REPL 处理(简化版):

```python
async def run_repl(session: Engine, deps: RunnerDeps):
    while True:
        line = await prompt_async("writer> ")
        input_text = compose_pending_input(line, session.pending_interrupt)
        session.clear_pending_interrupt()
        async for event in run_runner(build_ctx(input_text), deps):
            if isinstance(event, Interrupt):
                session.set_pending_interrupt(event)
                render_interactive_prompt(event)  # choice/text/confirm 分发
            elif isinstance(event, Done):
                session.record_turn(line, event.reason)
                break
            else:
                render_event(event)
```

注意:**当前实现没有保留旧文档里 `AgentInterrupt` / `UserReply` 这两个 dataclass**。Interrupt 是 engine 事件,UserReply 直接是下一次 turn 的 `user_input` 字符串(无需独立类型)。多轮 resume 由 `Engine.pending_interrupt` 字段串起来,跨 `run_runner()` 调用自动拼接。

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
