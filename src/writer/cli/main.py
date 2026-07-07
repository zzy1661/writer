import asyncio
import os
import re
import sys
import tempfile
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
from writer.config import get_settings, load_env_file, load_project_settings, refresh_settings
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
from writer.engine.deps import production_deps
from writer.project import (
    STATE_DESCRIPTIONS,
    ProjectState,
    create_new_workspace,
    create_workspace,
    discover_project_root,
    inspect_project,
    normalize_genres,
    prompt_genres,
    safe_cwd,
)
from writer.project.init_brief import apply_init_brief
from writer.session import EngineSession, compose_pending_input
from writer.skills import SkillRegistry, built_skill_registry

app = typer.Typer(
    name="writer",
    help="长篇小说写作 Agent CLI",
    no_args_is_help=False,
)
console = Console()

EXIT_COMMANDS = {"/退出", "/quit", "/q", "exit", "quit"}
HELP_COMMANDS = {"/帮助", "/help", "help"}

# Static REPL commands that aren't owned by a Skill. /大纲, /目录, /续写,
# /改 used to live here too — they are now served by the SkillRegistry
# (see ``build_repl_commands``).
STATIC_REPL_COMMANDS = [
    ("/init", "初始化小说项目"),
    ("/创作", "创作指定章节或下一章"),
    ("/审核", "审核当前正文"),
    ("/查看", "查看项目文件或目录"),
    ("/搜索", "搜索项目文本"),
    ("/字数统计", "统计项目或文件字数"),
    ("/状态", "查看当前项目状态"),
    ("/帮助", "显示帮助"),
    ("/退出", "退出 writer"),
]

# ``REPL_COMMANDS`` is kept as a module-level constant for backwards
# compatibility with existing tests / completion behaviour. Derived from
# the default skill registry at import time so the list still includes
# every currently-registered Skill command.
REPL_COMMANDS: list[tuple[str, str]] = list(STATIC_REPL_COMMANDS) + built_skill_registry().help_entries()


def build_repl_commands(skill_registry: SkillRegistry) -> list[tuple[str, str]]:
    """Return the full ``/帮助`` table: static commands + skills.

    Static commands (init / 状态 / 帮助 / 退出, plus the not-yet-Skill
    /创作 /审核 / 查看 / 搜索 / 字数统计) come first so the help table
    stays stable across Skill additions. Skills follow in alphabetical
    order (driven by :meth:`SkillRegistry.commands`).
    """

    return list(STATIC_REPL_COMMANDS) + skill_registry.help_entries()


REPL_PROMPT = "writer> "
try:
    _DEFAULT_HISTORY_DIR = Path.home() / ".config" / "writer"
except RuntimeError:
    _DEFAULT_HISTORY_DIR = Path(tempfile.gettempdir()) / "writer"
HISTORY_DIR = _DEFAULT_HISTORY_DIR
HISTORY_FILE = HISTORY_DIR / "history"

# Slash 命令补全词：必须包含前导 ``/``，否则 ``/`` 会被当成词边界，
# ``word_before_cursor`` 恒为空 → 不过滤前缀，且选中后出现 ``//命令``。
SLASH_CMD_PATTERN = re.compile(r"[/\w\u4e00-\u9fff]+")


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


def print_repl_help(skill_registry: SkillRegistry | None = None) -> None:
    """Render the first-pass command list used inside the REPL.

    When ``skill_registry`` is provided, draws the help entries from it
    so a plugin that registers a new skill is automatically reflected
    in ``/帮助`` without restarting the process.
    """

    if skill_registry is None:
        skill_registry = built_skill_registry()
    table = Table(title="可用命令")
    table.add_column("命令", style="cyan", no_wrap=True)
    table.add_column("说明")

    for command, description in build_repl_commands(skill_registry):
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
                f"可用题材（输入后回车；其它值视为 other）：{', '.join(_init_prompt_genre_labels())}"
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


def _resolve_history_file(
    history_file: Path | None | object = None,
) -> Path | None:
    """Return a writable REPL history path, or ``None`` to disable history.

    Preference order:

    1. Explicit ``history_file`` argument (tests / callers)
    2. ``$XDG_CONFIG_HOME/writer/history``
    3. ``~/.config/writer/history``
    4. ``$TMPDIR`` / system temp (PyInstaller / sandbox fallback)
    5. ``./.writer/history`` in the current working directory
    """

    if history_file is NO_HISTORY:
        return None
    if isinstance(history_file, Path):
        candidates = [history_file]
    else:
        candidates = []
        xdg_config = os.environ.get("XDG_CONFIG_HOME", "").strip()
        if xdg_config:
            candidates.append(Path(xdg_config) / "writer" / "history")
        candidates.append(HISTORY_FILE)
        candidates.append(Path(tempfile.gettempdir()) / "writer-repl-history")
        cwd = safe_cwd()
        if cwd is not None:
            candidates.append(cwd / ".writer" / "history")

    for candidate in candidates:
        try:
            candidate.parent.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        return candidate
    return None


def build_prompt_session(
    history_file: Path | None | object = None,
    *,
    skill_registry: SkillRegistry | None = None,
) -> PromptSession[str]:
    """Construct a prompt session with persistent history + tab completion.

    Pass ``history_file=NO_HISTORY`` to disable history entirely (useful in
    tests). Passing ``None`` (the default) uses the user-level history file.

    ``skill_registry`` is consulted for the completion word list so a
    plugin can register new slash commands and they'll show up in
    tab-completion without rebuilding the session. When omitted, the
    default :func:`writer.skills.built_skill_registry` is used — keeping
    the original zero-arg call sites (``build_prompt_session()`` in
    :func:`_build_repl_prompt_session` and tests) working unchanged.
    """
    history_path = _resolve_history_file(history_file)
    history: FileHistory | None = None
    if history_path is not None:
        try:
            history = FileHistory(str(history_path))
        except OSError:
            history = None

    if skill_registry is None:
        skill_registry = built_skill_registry()
    completion_words = (
        [cmd for cmd, _ in build_repl_commands(skill_registry)] + ["exit", "quit"]
    )
    completer = WordCompleter(
        completion_words, ignore_case=True, pattern=SLASH_CMD_PATTERN
    )

    return PromptSession(
        history=history,
        completer=completer,
        complete_while_typing=True,
    )


def _build_repl_prompt_session() -> PromptSession[str] | None:
    """Build a prompt session for interactive REPL, or fall back to plain input."""

    if not sys.stdin.isatty():
        return None
    try:
        return build_prompt_session()
    except OSError:
        return None


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

    load_env_file(safe_cwd())
    discovered = discover_project_root()
    if discovered is not None:
        load_project_settings(discovered)
    refresh_settings()

    # One EngineSession for the lifetime of the REPL — owns session_id,
    # deps, turn history, and pending Interrupt state.
    engine_session = EngineSession()
    if discovered is not None:
        engine_session.set_project_root(discovered)
        console.print(
            f"[dim]已自动绑定项目: {discovered} "
            f"({STATE_DESCRIPTIONS[ProjectState(engine_session.project_state)]})[/dim]"
        )
    elif safe_cwd() is None:
        console.print(
            "[yellow]警告：当前 shell 的工作目录已失效（可能被移动或删除）。"
            "请先 [bold]cd[/bold] 到一个有效目录，或使用 [bold]/init <项目名>[/bold] 重新初始化。[/yellow]"
        )

    # ``skill_registry`` lives on ``engine_session.deps`` (see
    # ``EngineDeps.skill_registry``); passing it through to the prompt
    # session + ``/帮助`` renderer keeps the help table and tab
    # completion in sync with whatever skills are registered for this
    # REPL run — including entry-point plugins discovered at import
    # time.
    skill_registry = engine_session.deps.skill_registry

    if prompt_session is None and sys.stdin.isatty():
        prompt_session = build_prompt_session(skill_registry=skill_registry)

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


def _init_prompt_genre_labels() -> list[str]:
    from writer.project.genre import GENRE_OPTIONS

    return list(GENRE_OPTIONS)


def _normalize_cli_genre(raw: str) -> str:
    """Map a CLI-side genre string to a canonical key (legacy single-genre helper)."""

    from writer.project.genre import normalize_genre_token

    return normalize_genre_token(raw)


def _parse_repl_init_argv(text: str) -> tuple[str, Path, bool, str | None]:
    """Parse ``"/init --name 双生 --dir . --genre 言情"`` style input.

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
    parser.add_argument("--dir", "-d", default=".", dest="directory")
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
    genres: list[str] | None = None,
    brief: str | None = None,
    skip_brief: bool = False,
) -> str:
    """Shared backend for the Typer ``init`` subcommand and the REPL ``/init``.

    Returns the canonical genre label used (for session binding).
    """
    genre_list = normalize_genres(genres if genres is not None else ([genre] if genre else ["other"]))
    from writer.project.genre import format_genre_line, primary_genre

    resolved_genre = format_genre_line(genre_list) or primary_genre(genre_list)
    try:
        workspace = create_workspace(
            name,
            directory,
            force=force,
            genres=genre_list,
            with_ideas_dir=True,
        )
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]已创建小说项目：[/green]{workspace.root}")
    console.print(f"题材：{resolved_genre}")
    for path in workspace.created_files:
        console.print(f"  - {path}")

    _maybe_apply_init_brief(workspace.root, brief=brief, skip_brief=skip_brief)

    console.print(
        "[dim]提示：在同一目录执行 `uv run writer` 进入 REPL 时会自动绑定此项目。[/dim]"
    )
    return resolved_genre


def _maybe_apply_init_brief(
    project_root: Path,
    *,
    brief: str | None,
    skip_brief: bool,
) -> None:
    if skip_brief:
        return

    user_brief = brief
    if user_brief is None and sys.stdin.isatty():
        console.print(
            "\n[cyan]请用自然语言描述你的小说创意与基本要求[/cyan]"
            "（直接回车跳过）："
        )
        user_brief = typer.prompt("", default="", show_default=False)

    if not user_brief or not user_brief.strip():
        return

    load_project_settings(project_root)
    refresh_settings()
    deps = production_deps(project_root=project_root)
    result = apply_init_brief(project_root, user_brief.strip(), deps.story_consultant)
    console.print(f"[green]已写入 创意/核心创意.md[/green]（来源: {result.source}）")
    console.print("[green]已更新 AGENT.md 基本要求[/green]")


@app.command("new")
def new_project_cmd(
    name: Annotated[str, typer.Argument(help="小说书名（目录名）")],
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="项目创建到哪个目录下"),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option("--force", help="允许覆盖缺失的初始化文件"),
    ] = False,
    genre: Annotated[
        list[str] | None,
        typer.Option(
            "--genre",
            "-g",
            help="小说题材，可重复指定或逗号分隔（历史 / 言情 / 玄幻 / …）",
        ),
    ] = None,
) -> None:
    """创建带 ``.writer/`` 元数据与 ``创意/`` 目录的新书项目。"""
    selected = normalize_genres(genre) if genre else prompt_genres(console)

    try:
        workspace = create_new_workspace(
            name,
            directory,
            force=force,
            genres=selected,
        )
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(code=1) from exc

    from writer.project.genre import format_genre_line

    label = format_genre_line(selected) or "other"
    console.print(f"[green]已创建新书项目：[/green]{workspace.root}")
    console.print(f"题材：{label}")
    for path in workspace.created_files:
        console.print(f"  - {path}")
    console.print(
        "[dim]项目 LLM 配置位于 .writer/config（优先级高于 .env）。[/dim]"
    )
