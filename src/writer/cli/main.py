import asyncio
import re
import sys
from pathlib import Path
from typing import Annotated
from uuid import uuid4

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from writer import __version__
from writer.agent import NovelAgent
from writer.config import get_settings
from writer.engine import (
    ActionEvent,
    Done,
    EngineContext,
    ErrorEvent,
    Interrupt,
    TextChunk,
    ToolCall,
    ToolResult,
    production_deps,
    run_engine,
)
from writer.project import create_workspace

app = typer.Typer(
    name="writer",
    help="长篇小说写作 Agent CLI",
    no_args_is_help=False,
)
console = Console()

EXIT_COMMANDS = {"/退出", "/quit", "/q", "exit", "quit"}
HELP_COMMANDS = {"/帮助", "/help", "help"}

REPL_COMMANDS = [
    ("/init", "初始化小说项目"),
    ("/大纲", "生成或查看大纲"),
    ("/目录", "生成或查看章节目录"),
    ("/写", "写指定章节或下一章"),
    ("/续写", "继续未完成章节"),
    ("/改", "修改章节内容"),
    ("/审核", "审核当前正文"),
    ("/状态", "查看当前项目状态"),
    ("/帮助", "显示帮助"),
    ("/退出", "退出 writer"),
]

REPL_PROMPT = "writer> "
HISTORY_DIR = Path.home() / ".config" / "writer"
HISTORY_FILE = HISTORY_DIR / "history"

# 支持中文的补全词匹配模式
WORD_PATTERN = re.compile(r"^[\w\u4e00-\u9fff]+$")


def version_callback(value: bool) -> None:
    if value:
        console.print(f"writer-agent {__version__}")
        raise typer.Exit


def print_welcome() -> None:
    """Render the minimal REPL landing page."""
    console.print(
        Panel.fit(
            f"[bold cyan]Writer Agent[/bold cyan] [dim]v{__version__}[/dim]\n"
            "长篇小说写作控制台已启动。\n\n"
            "输入 [bold]/帮助[/bold] 查看可用命令，输入 [bold]/退出[/bold] 结束会话。",
            title="欢迎",
            border_style="cyan",
        )
    )


def print_repl_help() -> None:
    """Render the first-pass command list used inside the REPL."""
    table = Table(title="可用命令")
    table.add_column("命令", style="cyan", no_wrap=True)
    table.add_column("说明")

    for command, description in REPL_COMMANDS:
        table.add_row(command, description)

    console.print(table)


def handle_repl_input(line: str) -> bool:
    """Handle one REPL input line.

    Returns False when the loop should stop.
    """
    text = line.strip()
    if not text:
        return True

    if text in EXIT_COMMANDS:
        console.print("[green]已退出 writer。[/green]")
        return False

    if text in HELP_COMMANDS:
        print_repl_help()
        return True

    if text == "/状态":
        console.print("[blue]当前状态：[/blue]控制台已启动，项目状态机将在后续步骤接入。")
        return True

    # 框架命令（退出/帮助/状态）之外的所有输入——斜杠命令与自然语言
    # 一律交给 agent engine 统一分发，避免 CLI 层重复维护命令路由。
    asyncio.run(_run_engine(text, console))
    return True


async def _run_engine(user_input: str, console: Console) -> None:
    """Drive the agent engine for one natural-language turn."""
    ctx = EngineContext(
        user_input=user_input,
        project_root=None,
        project_state="S0",
        session_id=str(uuid4()),
    )
    deps = production_deps()

    async for event in run_engine(ctx, deps):
        match event:
            case TextChunk(text=chunk):
                # engine output is plain text — disable Rich markup so
                # tokens like "[engine]" stay literal in the REPL
                console.print(chunk, end="", markup=False, highlight=False)
            case ActionEvent(action=a):
                console.print(f"[dim]→ {a.action_type}[/dim]")
            case ToolCall(name=n):
                console.print(f"[yellow]⚙ {n}[/yellow]")
            case ToolResult(name=name, output=output):
                console.print(f"[green]✓ {name}: {output}[/green]")
            case Interrupt(prompt=p):
                console.print(f"[cyan]? {p}[/cyan]")
            case Done(reason=r):
                console.print(f"[green]✓ {r}[/green]\n")
            case ErrorEvent(message=m):
                console.print(f"[red]✗ {m}[/red]")


NO_HISTORY: object = object()


def build_prompt_session(
    history_file: Path | None | object = None,
) -> PromptSession[str]:
    """Construct a prompt session with persistent history + tab completion.

    Pass ``history_file=NO_HISTORY`` to disable history entirely (useful in
    tests). Passing ``None`` (the default) uses the user-level history file.
    """
    if history_file is NO_HISTORY:
        history: FileHistory | None = None
    else:
        history_path = (
            history_file if isinstance(history_file, Path) else HISTORY_FILE
        )
        history_path.parent.mkdir(parents=True, exist_ok=True)
        history = FileHistory(str(history_path))

    completion_words = [cmd for cmd, _ in REPL_COMMANDS] + ["exit", "quit"]
    completer = WordCompleter(completion_words, ignore_case=True, pattern=WORD_PATTERN)

    return PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
    )


def _read_line(session: PromptSession[str] | None, prompt: str) -> str:
    """Read one line from stdin.

    Uses prompt-toolkit only when stdin is a TTY (interactive terminal);
    falls back to plain ``input()`` for piped input, which keeps CliRunner
    tests and ``writer < commands.txt`` usage stable.
    """
    if session is not None:
        return session.prompt(prompt)
    return input(prompt)


def run_repl(session: PromptSession[str] | None = None) -> None:
    """Start the interactive writer command loop."""
    print_welcome()

    if session is None:
        session = build_prompt_session() if sys.stdin.isatty() else None

    while True:
        try:
            line = _read_line(session, REPL_PROMPT)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[green]已退出 writer。[/green]")
            break

        if not handle_repl_input(line):
            break


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, help="显示版本号"),
    ] = None,
) -> None:
    """长篇小说写作 Agent CLI。"""
    if ctx.invoked_subcommand is None:
        run_repl()


@app.command()
def doctor() -> None:
    """检查当前配置是否可用。"""
    settings = get_settings()

    table = Table(title="writer-agent doctor")
    table.add_column("项目")
    table.add_column("状态")
    table.add_row("模型", settings.model)
    table.add_row("Base URL", settings.base_url)
    table.add_row("API Key", "已配置" if settings.has_api_key else "未配置")
    table.add_row("Temperature", str(settings.temperature))

    console.print(table)


@app.command("new")
def new_project(
    name: Annotated[str, typer.Argument(help="小说项目名称")],
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="项目创建到哪个目录下"),
    ] = Path("novels"),
    force: Annotated[
        bool,
        typer.Option("--force", help="允许覆盖缺失的初始化文件"),
    ] = False,
) -> None:
    """创建一个小说项目工作区。"""
    try:
        workspace = create_workspace(name, directory, force=force)
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]已创建小说项目：[/green]{workspace.root}")
    for path in workspace.created_files:
        console.print(f"  - {path}")


@app.command()
def outline(
    idea: Annotated[str, typer.Argument(help="一句话小说创意")],
) -> None:
    """根据一句话创意生成最小大纲。"""
    settings = get_settings()
    agent = NovelAgent(settings)
    result = agent.draft_outline(idea)

    console.print(f"[bold]{result.title}[/bold]")
    console.print(result.premise)
    for chapter in result.chapters:
        console.print(f"- {chapter}")