"""REPL 交互层：交互式 writer 命令循环 + 引擎事件桥接。

与 Typer 子命令层（``commands``）解耦；``/init`` flag 形式复用
``_init_backend.init_project``，避免 CLI 层重复维护项目创建逻辑。
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from argparse import ArgumentParser
from pathlib import Path

import typer
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from rich.console import Console
from rich.panel import Panel
from rich.table import Table

from writer import __version__
from writer.config import load_env_file, load_project_settings, refresh_settings
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
from writer.project import (
    STATE_DESCRIPTIONS,
    ProjectState,
    discover_project_root,
    inspect_project,
    safe_cwd,
)
from writer.session import EngineSession, compose_pending_input
from writer.skills import DirectiveRegistry, built_directive_registry

console = Console()

EXIT_COMMANDS = {"/退出", "/quit", "/q", "exit", "quit"}
HELP_COMMANDS = {"/帮助", "/help", "help"}

# 不属于任何 Skill 的静态 REPL 命令。``/大纲``、``/目录`` 之前也
# 放在这里 —— 现在由 DirectiveRegistry 提供（见 ``build_repl_commands``）。
STATIC_REPL_COMMANDS = [
    ("/init", "初始化小说项目"),
    ("/创作", "创作指定章节或下一章"),
    ("/审核", "审核当前正文"),
    ("/字数统计", "统计项目或文件字数"),
    ("/状态", "查看当前项目状态"),
    ("/帮助", "显示帮助"),
    ("/退出", "退出 writer"),
]

# ``REPL_COMMANDS`` 作为模块级常量保留，以兼容现有测试 / 补全行为。
# 在 import 时从默认 skill registry 派生，因此列表仍包含当前所有
# 已注册的 Skill 命令。
REPL_COMMANDS: list[tuple[str, str]] = list(STATIC_REPL_COMMANDS) + built_directive_registry().help_entries()


def build_repl_commands(directive_registry: DirectiveRegistry) -> list[tuple[str, str]]:
    """返回 ``/帮助`` 完整表格：静态命令 + skills。

    静态命令（init / 状态 / 帮助 / 退出，以及尚未 Skill 化的
    /创作 /审核 / 查看 / 搜索 / 字数统计）放在前面，让帮助表
    在 Skill 增加时仍保持稳定。Skills 按字母顺序紧随其后
    （由 :meth:`DirectiveRegistry.commands` 驱动）。
    """

    return list(STATIC_REPL_COMMANDS) + directive_registry.help_entries()


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


def print_welcome() -> None:
    """渲染极简的 REPL 落地页。"""
    console.print(
        Panel.fit(
            f"[bold cyan]Writer Agent[/bold cyan] [dim]v{__version__}[/dim]\n"
            "长篇小说写作控制台已启动。\n\n"
            "输入 [bold]/帮助[/bold] 查看可用命令，输入 [bold]/退出[/bold] 结束会话。",
            title="欢迎",
            border_style="cyan",
        )
    )


def print_repl_help(directive_registry: DirectiveRegistry | None = None) -> None:
    """渲染 REPL 内首次使用的命令列表。

    提供 ``directive_registry`` 时从它拉取帮助条目，以便注册了新 skill
    的插件无需重启进程即可反映在 ``/帮助`` 中。
    """

    if directive_registry is None:
        directive_registry = built_directive_registry()
    table = Table(title="可用命令")
    table.add_column("命令", style="cyan", no_wrap=True)
    table.add_column("说明")

    for command, description in build_repl_commands(directive_registry):
        table.add_row(command, description)

    console.print(table)


def _init_prompt_genre_labels() -> list[str]:
    from writer.project.genre import GENRE_OPTIONS

    return list(GENRE_OPTIONS)


def _parse_repl_init_argv(text: str) -> tuple[str, Path, bool, str | None]:
    """解析 ``"/init --name 双生 --dir . --genre 言情"`` 风格的输入。

    返回 ``(name, directory, force, genre)``。``--name`` 缺失或
    为空时抛 ``ValueError``。REPL 形式不支持位置参数 ``name``
    （它是单行 shell-ish 字符串，``/init`` 后第一个 token 必须
    是 flag）—— 显式 ``--name`` 让解析保持确定性，并在省略时
    给出更清晰的报错。
    """
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


def handle_repl_input(line: str, session: EngineSession) -> bool:
    """处理一行 REPL 输入。

    循环应当停止时返回 False。
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
        # ``/init`` 单用（无参数）走 engine 派发；只有 flag 形式
        # （例如 ``/init --name 双生 --genre 言情``）走本代码路径，
        # 与 Typer 子命令行为一致。
        # 按 REPL 形式解析命令后的 argv 风格 flag。
        # 支持的 flag 与 Typer 子命令对齐：--name, --dir/-d,
        # --genre/-g, --force。缺失 --genre 时走相同的 Typer 风格
        # 提示（4 选 1 → 自由文本后续输入）。
        try:
            name, directory, force, genre = _parse_repl_init_argv(text)
        except ValueError as exc:
            console.print(f"[red]错误：{exc}[/red]")
            return True

        if genre is None:
            # 交互式提示 —— 把规范标签作为提示展示；
            # 实际提示按项目决定为自由文本。
            console.print(
                f"可用题材（输入后回车；其它值视为 other）：{', '.join(_init_prompt_genre_labels())}"
            )
            picked = typer.prompt("请选择小说题材", default="其他")
            genre_arg: str | None = picked
        else:
            genre_arg = genre

        # 跨模块：repl → _init_backend。函数内懒加载避免模块加载期
        # 拉进 _init_backend（防御性，无实际循环风险）。
        from writer.cli._init_backend import init_project

        try:
            resolved_genre = init_project(
                name,
                directory,
                force=force,
                genre=genre_arg,
            )
        except typer.Exit:
            return True

        # 把刚创建的项目绑定到当前 session，让后续 engine 轮次能找到
        # 正确的 RAG 文件 / Agent。
        try:
            session.set_project_root(directory / name)
            session.refresh_project_genre()
        except Exception:  # noqa: BLE001 — set_project_root 对路径宽容
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
    """为单轮自然语言驱动 agent engine。

    使用 ``session.deps``（REPL 启动时一次性构建）和
    ``session.session_id``（跨轮次冻结）。若上一轮产出了 ``Interrupt``
    事件，则把待回答的 prompt 与用户输入拼好后喂给引擎。
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
                # engine 输出是纯文本 —— 关闭 Rich markup，让
                # 类似 "[engine]" 这样的 token 在 REPL 中保持字面值。
                console.print(chunk, end="", markup=False, highlight=False)
            case ActionEvent(action=a):
                console.print(f"[dim]→ {a.action_type}[/dim]")
            case ToolCall(name=n):
                console.print(f"[yellow]⚙ {n}[/yellow]")
            case ToolResult(name=name, output=output):
                console.print(f"[green]✓ {name}: {output}[/green]")
            case Interrupt() as interrupt:
                # 展示 prompt 并暂存到下一轮
                console.print(f"[cyan]? {interrupt.prompt}[/cyan]")
                session.set_pending_interrupt(interrupt)
            case Done(reason=r, payload=payload):
                if payload is not None and "project_root" in payload:
                    session.set_project_root(Path(str(payload["project_root"])))
                else:
                    session.refresh_project_state()
                console.print(f"[green]✓ {r}[/green]\n")
                # Per arch-optimizer M5（2026-07-07）：从 aborted payload
                # 中暴露 ``project_state``，让用户知道引擎*为何*拒绝了
                # 命令（例如「S1 状态不允许 /创作」）。没有它时，
                # 一次 aborted Done 只会让用户一头雾水。
                if r == "aborted" and payload is not None and "project_state" in payload:
                    state_value = str(payload["project_state"])
                    # STATE_DESCRIPTIONS 以 ProjectState enum 为键；
                    # payload 携带字符串形式。先尝试 enum 查找，
                    # 字符串不是已知 ProjectState 成员时回退到原值。
                    try:
                        description = STATE_DESCRIPTIONS[ProjectState(state_value)]
                    except (KeyError, ValueError):
                        description = ""
                    label = f"{state_value}（{description}）" if description else state_value
                    console.print(f"[yellow]当前状态: {label}[/yellow]")
                # PR3：当工作流返回 status="pending"（例如带
                # decision=needs_rewrite 的 review_chapter）会以 aborted
                # 形式呈现并附带 decision 指标。告诉用户工作流判定了
                # 什么，以便他们知道要用更清晰的任务重新跑 /创作。
                if r == "aborted" and payload is not None and "decision" in payload:
                    decision = str(payload["decision"])
                    console.print(f"[yellow]工作流判定: {decision}[/yellow]")
                # Per LLM 工具循环增补（2026-07-08）：当 LLM 工具循环
                # 触及 ``MAX_LOOP_STEPS`` 预算时，引擎会产出
                # ``Done(tool_loop_completed)``，payload 中包含调用次数
                # 与最后一次工具输出。把它们暴露出来，让用户知道循环已
                # 耗尽预算，并掌握后续提出更窄追问所需的数据。
                if r == "tool_loop_completed" and payload is not None:
                    calls = payload.get("tool_calls_made", 0)
                    last = str(payload.get("last_output", ""))
                    tail = last if len(last) <= 200 else last[:200] + "..."
                    console.print(
                        f"[dim]LLM 工具循环已结束（{calls} 次调用）；最近结果: {tail}[/dim]"
                    )
                # Per real-writing-pipeline PR1（2026-07-09）：当工作流
                # 返回 ``WorkflowResult(status="completed")`` 时，引擎
                # 产出 ``Done(reason="workflow_completed")``，payload
                # 中带有 artifacts + metrics。把它们渲染出来，让用户
                # 看到工作流产出了什么而无需重跑。
                if r == "workflow_completed" and payload is not None:
                    artifacts = payload.get("artifacts") or {}
                    metrics = payload.get("metrics") or {}
                    if artifacts:
                        lines = "\n".join(
                            f"  [dim]{key}[/dim] {value}" for key, value in artifacts.items()
                        )
                        console.print(f"[dim]artifacts:\n{lines}[/dim]")
                    if metrics:
                        metric_lines = ", ".join(
                            f"{key}={value}" for key, value in metrics.items()
                        )
                        console.print(f"[dim]metrics: {metric_lines}[/dim]")
                session.record_turn(user_input, r)
                session.clear_pending_interrupt()
            case ErrorEvent(message=m):
                console.print(f"[red]✗ {m}[/red]")


NO_HISTORY: object = object()


def _resolve_history_file(
    history_file: Path | None | object = None,
) -> Path | None:
    """返回可写的 REPL history 路径，或 ``None`` 禁用 history。

    优先级：

    1. 显式传入的 ``history_file`` 参数（测试 / 调用方）
    2. ``$XDG_CONFIG_HOME/writer/history``
    3. ``~/.config/writer/history``
    4. ``$TMPDIR`` / 系统临时目录（PyInstaller / 沙箱回退）
    5. 当前工作目录下的 ``./.writer/history``
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
    directive_registry: DirectiveRegistry | None = None,
) -> PromptSession[str]:
    """构造带持久化历史与 Tab 补全的 prompt session。

    传入 ``history_file=NO_HISTORY`` 可完全禁用 history（测试中很有用）。
    传入 ``None``（默认）使用用户级 history 文件。

    ``directive_registry`` 用于补全词列表，插件注册新斜杠命令后
    无需重建 session 即可在 Tab 补全中体现。省略时使用默认的
    :func:`writer.skills.built_directive_registry` —— 保持零参调用
    （``_build_repl_prompt_session`` 与测试中）的不变性。
    """
    history_path = _resolve_history_file(history_file)
    history: FileHistory | None = None
    if history_path is not None:
        try:
            history = FileHistory(str(history_path))
        except OSError:
            history = None

    if directive_registry is None:
        directive_registry = built_directive_registry()
    completion_words = (
        [cmd for cmd, _ in build_repl_commands(directive_registry)] + ["exit", "quit"]
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
    """为交互式 REPL 构建 prompt session，否则回退到原生 input。"""

    if not sys.stdin.isatty():
        return None
    try:
        return build_prompt_session()
    except OSError:
        return None


def _read_line(session: PromptSession[str] | None, prompt: str) -> str:
    """从 stdin 读取一行。

    仅当 stdin 是 TTY（交互终端）时使用 prompt-toolkit；
    对管道输入回退到原生 ``input()``，让 CliRunner 测试与
    ``writer < commands.txt`` 用法保持稳定。
    """
    if session is not None:
        return session.prompt(prompt)
    return input(prompt)


def run_repl(prompt_session: PromptSession[str] | None = None) -> None:
    """启动交互式 writer 命令循环。"""
    print_welcome()

    load_env_file(safe_cwd())
    discovered = discover_project_root()
    if discovered is not None:
        load_project_settings(discovered)
    refresh_settings()

    # 一个 EngineSession 撑起 REPL 整个生命周期 —— 持有 session_id、
    # deps、轮次历史与待处理 Interrupt 状态。
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

    # ``directive_registry`` 位于 ``engine_session.deps``（见
    # ``EngineDeps.directive_registry``）；把它透传给 prompt session
    # 与 ``/帮助`` 渲染器，让帮助表和 Tab 补全与本次 REPL 运行所注册
    # 的 skills（包括 import 时由 entry point 发现的插件）保持同步。
    directive_registry = engine_session.deps.directive_registry

    if prompt_session is None and sys.stdin.isatty():
        prompt_session = build_prompt_session(directive_registry=directive_registry)

    while True:
        try:
            line = _read_line(prompt_session, REPL_PROMPT)
        except (EOFError, KeyboardInterrupt):
            console.print("\n[green]已退出 writer。[/green]")
            break

        if not handle_repl_input(line, engine_session):
            break
