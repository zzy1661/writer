# 技术难点与解决方案备忘

## 业务需求理解

本项目是面向中文长篇小说创作的 CLI Agent。用户通过 REPL 与命令行工具完成从创意输入、题材定位、大纲生成、目录生成、章节写作、审核、修订、续写到跨章节检查的完整闭环。

项目的核心业务要求包括:

- 项目目录采用中文结构,以 `AGENT.md` 作为唯一状态总览。
- `大纲/大纲.md` 是唯一正典,正文生成必须遵循大纲、人物、世界观、伏笔和史实。
- MVP 分阶段交付:阶段一打通基础命令、`/init` 和 `/目录`;阶段二补齐 `/创意`、`/伏笔`、`/大纲`、`/骨架`;阶段三实现 `/创作` 与 `/审核`。
- Agent 核心采用 LangGraph 多阶段流程,角色包括编剧顾问、历史顾问、校对和综合审核。
- 长篇写作需要 RAG、章节摘要、金字塔记忆、伏笔管理和跨章节审计支撑。
- CLI 需要具备流式输出、多行输入、补全、确认、中断恢复和可观测性。

## 全局最小闭环伪代码

```python
def handle_user_input(project_root, user_input: str) -> None:
    action = intent_router.route(user_input, detect_state(project_root))

    validate_command(project_root, action.command)

    if action.action_type == "start_workflow":
        state = {
            "project_root": str(project_root),
            "chapter_id": locate_chapter(action.arguments),
        }
        context = prep_context(state["chapter_id"], task=user_input)
        result = writer_graph.invoke({**state, "context": context})
        render_result(result)
        return

    if action.action_type == "call_tool":
        result = tool_registry.call(action.tool_name, action.arguments)
        render_result(result)
        return

    if action.action_type == "ask_user":
        reply = repl_handle_interrupt(action.user_prompt)
        resume_workflow(reply)
        return

    render_result(action.answer)
```

## 核心依赖版全局入口示例

```python
from pathlib import Path

import typer
from rich.console import Console
from langgraph.graph import StateGraph


app = typer.Typer()
console = Console()


@app.command()
def repl(project: Path = Path.cwd()) -> None:
    """启动 Writer Agent REPL。"""
    console.print(f"[green]项目目录:[/green] {project}")
    writer_graph: StateGraph = build_writer_graph()

    while True:
        user_input = input("writer> ")
        if user_input in {"/退出", "/quit", "/q"}:
            break

        action = intent_router.route(user_input, detect_state(project))
        if action.action_type == "start_workflow":
            result = writer_graph.invoke(
                {
                    "project_root": str(project),
                    "user_input": user_input,
                }
            )
            console.print(result)
        else:
            console.print(action)
```

## 备忘录清单

- [01-项目状态机与命令可用性](./01-项目状态机与命令可用性.md)
- [02-正典文件与多源写入一致性](./02-正典文件与多源写入一致性.md)
- [03-长篇上下文管理与RAG检索](./03-长篇上下文管理与RAG检索.md)
- [04-LangGraph多阶段编排与子代理隔离](./04-LangGraph多阶段编排与子代理隔离.md)
- [05-LLM提供商路由与流式输出](./05-LLM提供商路由与流式输出.md)
- [06-长任务质量控制与自动回流](./06-长任务质量控制与自动回流.md)
- [07-工具注册与文件权限安全](./07-工具注册与文件权限安全.md)
- [08-REPL交互体验与命令解析](./08-REPL交互体验与命令解析.md)
- [09-历史题材史实校验](./09-历史题材史实校验.md)
- [10-伏笔生命周期与跨章节一致性](./10-伏笔生命周期与跨章节一致性.md)
- [11-检查点恢复与可观测性](./11-检查点恢复与可观测性.md)
- [12-RAG与检索实现方案](./12-RAG与检索实现方案.md)
- [13-核心Tool设计](./13-核心Tool设计.md)
- [14-LLM用户交互与REPL中断协议](./14-LLM用户交互与REPL中断协议.md)
- [15-LangChain前台调度Agent设计](./15-LangChain前台调度Agent设计.md)
- [16-Agent架构模式与本项目选型](./16-Agent架构模式与本项目选型.md)
- [17-七种系统编排方式与本项目落地映射](./17-七种系统编排方式与本项目落地映射.md)
