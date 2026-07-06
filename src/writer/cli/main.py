import asyncio
import re
import sys
from pathlib import Path
from typing import Annotated

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from writer import __version__
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
    run_engine,
)
from writer.project import STATE_DESCRIPTIONS, ProjectState, create_workspace, inspect_project
from writer.session import EngineSession, compose_pending_input

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
    ("/创作", "创作指定章节或下一章"),
    ("/续写", "继续未完成章节"),
    ("/改", "修改章节内容"),
    ("/审核", "审核当前正文"),
    ("/查看", "查看项目文件或目录"),
    ("/搜索", "搜索项目文本"),
    ("/字数统计", "统计项目或文件字数"),
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


def handle_repl_input(line: str, session: EngineSession) -> bool:
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
        session.refresh_project_state()
        session.refresh_project_genre()
        snapshot = inspect_project(session.project_root)
        root = str(snapshot.root) if snapshot.root is not None else "未绑定"
        outline = (
            snapshot.outline_path.relative_to(snapshot.root).as_posix()
            if snapshot.root is not None and snapshot.outline_path is not None
            else "无"
        )
        console.print(
            f"[blue]当前状态：[/blue]session={session.session_id} "
            f"turns={len(session.turns)} "
            f"project_state={snapshot.state.value} "
            f"({STATE_DESCRIPTIONS[snapshot.state]}) "
            f"project_genre={session.project_genre} "
            f"project_root={root} "
            f"chapters={snapshot.chapter_count} "
            f"outline={outline}"
        )
        return True

    if text.startswith("/init ") and ("--" in text or " -" in text):
        # ``/init`` alone (no args) falls through to engine dispatch; only
        # flag-form inputs (e.g. ``/init --name 双生 --genre 言情``) take
        # this code path. Mirrors Typer subcommand behaviour.
        # Parse argv-style flags after the command for the REPL form.
        # Supported flags mirror the Typer subcommand: --name, --dir/-d,
        # --genre/-g, --force. Missing --genre falls through to the same
        # Typer-style prompt (4-option chooser → free-text follow-up).
        from writer.cli.main import _parse_repl_init_argv  # local import: forward-ref cycle

        try:
            name, directory, force, genre = _parse_repl_init_argv(text)
        except ValueError as exc:
            console.print(f"[red]错误：{exc}[/red]")
            return True

        if genre is None:
            # Interactive prompt — show the canonical labels as a hint;
            # actual prompt is free-text per project decision.
            console.print(
                f"可用题材（输入后回车；其它值视为 other）：{', '.join(_INIT_PROMPT_GENRES)}"
            )
            picked = typer.prompt("请选择小说题材", default="其他")
            genre_arg: str | None = picked
        else:
            genre_arg = genre

        try:
            resolved_genre = init_project(
                name,
                directory,
                force=force,
                genre=genre_arg,
            )
        except typer.Exit:
            return True

        # Bind the freshly-created project to the live session so subsequent
        # engine turns can find the right RAG files / Consultant.
        try:
            session.set_project_root(directory / name)
            session.refresh_project_genre()
        except Exception:  # noqa: BLE001 — set_project_root is path-tolerant
            pass
        console.print(f"[dim]session.project_genre={resolved_genre}[/dim]")
        return True

    # 框架命令（退出/帮助/状态）之外的所有输入——斜杠命令与自然语言
    # 一律交给 agent engine 统一分发，避免 CLI 层重复维护命令路由。
    asyncio.run(_run_engine(text, session, console))
    return True


async def _run_engine(
    user_input: str,
    session: EngineSession,
    console: Console,
) -> None:
    """Drive the agent engine for one natural-language turn.

    Uses ``session.deps`` (built once at REPL start) and
    ``session.session_id`` (frozen across turns). If the previous turn
    yielded an ``Interrupt`` event, the pending prompt is composed with
    the user's input before being fed to the engine.
    """
    session.refresh_project_state()
    composed_input = compose_pending_input(user_input, session.pending_interrupt)
    ctx = EngineContext(
        user_input=composed_input,
        project_root=session.project_root,
        project_state=session.project_state,
        session_id=str(session.session_id),
    )

    async for event in run_engine(ctx, session.deps):
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
            case Interrupt() as interrupt:
                # Show prompt and stash for next turn
                console.print(f"[cyan]? {interrupt.prompt}[/cyan]")
                session.set_pending_interrupt(interrupt)
            case Done(reason=r, payload=payload):
                if payload is not None and "project_root" in payload:
                    session.set_project_root(Path(str(payload["project_root"])))
                else:
                    session.refresh_project_state()
                console.print(f"[green]✓ {r}[/green]\n")
                # Per arch-optimizer M5 (2026-07-07): surface the
                # ``project_state`` from the aborted payload so the user
                # knows *why* the engine rejected the command (e.g. "S1
                # 状态不允许 /创作"). Without this, an aborted Done
                # leaves the user guessing.
                if r == "aborted" and payload is not None and "project_state" in payload:
                    state_value = str(payload["project_state"])
                    # STATE_DESCRIPTIONS is keyed on ProjectState enum;
                    # payload carries the str form. Try the enum lookup
                    # first, fall back to raw value if the string is
                    # not a known ProjectState member.
                    try:
                        description = STATE_DESCRIPTIONS[ProjectState(state_value)]
                    except (KeyError, ValueError):
                        description = ""
                    label = f"{state_value}（{description}）" if description else state_value
                    console.print(f"[yellow]当前状态: {label}[/yellow]")
                session.record_turn(user_input, r)
                session.clear_pending_interrupt()
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


def run_repl(prompt_session: PromptSession[str] | None = None) -> None:
    """Start the interactive writer command loop."""
    print_welcome()

    if prompt_session is None:
        prompt_session = build_prompt_session() if sys.stdin.isatty() else None

    # One EngineSession for the lifetime of the REPL — owns session_id,
    # deps, turn history, and pending Interrupt state.
    engine_session = EngineSession()

    while True:
        try:
            line = _read_line(prompt_session, REPL_PROMPT)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[green]已退出 writer。[/green]")
            break

        if not handle_repl_input(line, engine_session):
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
    genre: Annotated[
        str | None,
        typer.Option(
            "--genre",
            "-g",
            help="小说题材（历史 / 言情 / 玄幻，其他值视为 other 兜底）",
        ),
    ] = None,
) -> None:
    """创建一个小说项目工作区。"""
    resolved_genre = _resolve_genre_for_init(genre)
    try:
        workspace = create_workspace(
            name, directory, force=force, genre=resolved_genre
        )
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]已创建小说项目：[/green]{workspace.root}")
    console.print(f"题材：{resolved_genre}")
    for path in workspace.created_files:
        console.print(f"  - {path}")


# Four genre options shown in the interactive prompt when ``--genre``
# is missing. Selecting ``其他`` triggers a free-text follow-up prompt;
# anything the user types there is then treated as the ``other`` bucket.
_INIT_PROMPT_GENRES = ["历史", "言情", "玄幻", "其他"]


def _normalize_cli_genre(raw: str) -> str:
    """Map a CLI-side genre string (Chinese label or alias) to a canonical key.

    Returns ``"other"`` for empty input, whitespace, or any value outside
    the alias table — including user-typed custom strings like ``"都市悬疑"``
    or ``"科幻"`` (per ``fea-genre-aware-init`` decision: free input allowed,
    falls through to the four-act fallback).
    """
    key = (raw or "").strip().lower()
    if not key:
        return "other"
    aliases = {
        "历史": "历史",
        "history": "历史",
        "historical": "历史",
        "言情": "言情",
        "romance": "言情",
        "玄幻": "玄幻",
        "xuanhuan": "玄幻",
        "fantasy": "玄幻",
        "其他": "other",
        "other": "other",
    }
    return aliases.get(key, "other")


def _resolve_genre_for_init(raw: str | None) -> str:
    """Resolve the final genre string used by ``create_workspace``.

    ``raw`` is what the user passed (or what the REPL parser extracted).
    The REPL side supplies a non-null string already; the Typer side
    uses Typer's interactive prompt machinery to gather it. Either way,
    this function normalises to the same canonical key.
    """
    return _normalize_cli_genre(raw or "other")


def _parse_repl_init_argv(text: str) -> tuple[str, Path, bool, str | None]:
    """Parse ``"/init --name 双生 --dir novels --genre 言情"`` style input.

    Returns ``(name, directory, force, genre)``. Raises ``ValueError`` on
    missing/empty ``--name``. The REPL form does not support positional
    ``name`` (it's a single-line shell-ish string, so the first token
    after ``/init`` MUST be a flag) — explicit ``--name`` keeps parsing
    deterministic and produces a clearer error when omitted.
    """
    from argparse import ArgumentParser

    rest = text[len("/init"):].strip()
    parser = ArgumentParser(prog="init", add_help=False)
    parser.add_argument("--name", "-n", required=True, dest="name")
    parser.add_argument("--dir", "-d", default="novels", dest="directory")
    parser.add_argument("--genre", "-g", default=None, dest="genre")
    parser.add_argument(
        "--force", action="store_true", default=False, dest="force"
    )
    args = parser.parse_args(rest.split())
    if not args.name.strip():
        msg = "--name 不能为空"
        raise ValueError(msg)
    return (
        args.name.strip(),
        Path(args.directory),
        bool(args.force),
        args.genre,
    )


def init_project(
    name: str,
    directory: Path,
    *,
    force: bool = False,
    genre: str | None = None,
) -> str:
    """Shared backend for the Typer ``init`` subcommand and the REPL ``/init``.

    Returns the canonical genre used (never raises — surfaces errors via
    ``console.print`` and exit codes so the REPL driver doesn't crash).
    """
    resolved_genre = _normalize_cli_genre(genre or "other")
    try:
        workspace = create_workspace(
            name, directory, force=force, genre=resolved_genre
        )
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]已创建小说项目：[/green]{workspace.root}")
    console.print(f"题材：{resolved_genre}")
    for path in workspace.created_files:
        console.print(f"  - {path}")
    return resolved_genre


@app.command("init")
def init_project_cmd(
    name: Annotated[str, typer.Argument(help="小说项目名称")],
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="项目创建到哪个目录下"),
    ] = Path("novels"),
    force: Annotated[
        bool,
        typer.Option("--force", help="允许覆盖缺失的初始化文件"),
    ] = False,
    genre: Annotated[
        str | None,
        typer.Option(
            "--genre",
            "-g",
            help="小说题材（历史 / 言情 / 玄幻，其他视为兜底）",
            prompt=False,
        ),
    ] = None,
) -> None:
    """创建一个小说项目工作区（题材感知版）。"""
    if genre is None:
        # Interactive prompt — show the canonical labels as a hint; the
        # actual ``typer.prompt`` is free-text per the project decision
        # ("``其他`` 允许自由输入；任何非白名单值都落到 other 兜底").
        console.print(
            f"可用题材（输入后回车；其它值视为 other）：{', '.join(_INIT_PROMPT_GENRES)}"
        )
        picked = typer.prompt(
            "请选择小说题材",
            default="其他",
        )
    else:
        picked = genre
    init_project(name, directory, force=force, genre=picked)


@app.command()
def outline(
    idea: Annotated[str, typer.Argument(help="一句话小说创意")],
) -> None:
    """根据一句话创意生成最小大纲。"""
    # Reuse the same ``StoryConsultant`` the REPL would dispatch to (per
    # arch-optimizer M2 / Q1 2026-07-05). Previously the Typer subcommand
    # independently constructed ``NovelAgent(settings)`` while the REPL
    # used ``EngineSession.deps.story_consultant`` — two parallel paths,
    # so swapping the role implementation required changes in both
    # places. ``production_deps()`` is cheap; the extra cost over a
    # direct ``StoryConsultant(settings)`` call is negligible for a CLI
    # subcommand invoked once per process.
    from writer.engine.deps import production_deps

    deps = production_deps()
    result = deps.story_consultant.draft_outline(idea)

    console.print(f"[bold]{result.title}[/bold]")
    console.print(result.premise)
    for chapter in result.chapters:
        console.print(f"- {chapter}")
