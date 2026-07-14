"""REPL 交互层：交互式 writer 命令循环 + 引擎事件桥接。

与 Typer 子命令层（``commands``）解耦；REPL ``/init <创意>`` 简洁形式
复用 :func:`writer.cli._init_backend.apply_genre_and_brief` 完成
"补脚手架 + 更新题材行 + 写 brief"。

REPL 不再支持 ``/init --name X --dir Y`` flag 形式 —— 创建项目请用
CLI 子命令 ``writer new <书名>``（per 2026-07-14 收紧）。``/init``
后只允许跟故事核心创意。
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
import tempfile
from pathlib import Path

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
    ErrorEvent,
    Interrupt,
    TextChunk,
    ToolCall,
    ToolResult,
)
from writer.project import (
    STATE_DESCRIPTIONS,
    ProjectState,
    discover_project_root,
    inspect_project,
    prompt_genres,
    safe_cwd,
)
from writer.session import EngineSession
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


def _try_handle_repl_init_brief(text: str, session: EngineSession) -> bool:
    """REPL 简洁 ``/init <brief>`` 处理器。

    返回 ``True`` 表示已处理（消费输入），``False`` 表示不是 brief
    形式（让既有路径继续走）。短路条件：

    - 文本不是 brief 形式（``looks_like_creative_brief(rest)`` 为 ``False``）
    - ``session.project_root`` 与 ``discover_project_root()`` 都找不到项目
      （此时打印红色错误，仍返回 ``True`` —— 已处理，避免引擎再次询问）

    处理流程：

    1. 找 ``project_root = session.project_root or discover_project_root()``；
       找不到则提示「请先在 ``writer new`` 创建的目录内执行」并返回 ``True``。
    2. 当前题材回退（``session.project_genre`` 或 ``read_genre_from_agent``），
       打印「当前题材: <label>」+ 多选提示。
    3. ``prompt_genres(console, default=None)`` —— 每次让用户重选；
       非 TTY 走 ``["其他"]`` 兜底。
    4. :func:`writer.cli._init_backend.apply_genre_and_brief` 一步完成
       「补脚手架 + 更新题材行 + 写 brief」。
    5. ``session.refresh_project_genre()`` 同步缓存。
    6. 打印摘要：所选题材、新建文件数（>0 时）、题材行变更、brief 来源。
    """

    from writer.project.init_brief import extract_init_brief_text, looks_like_creative_brief

    rest = extract_init_brief_text(text)
    if not looks_like_creative_brief(rest):
        return False

    project_root = session.project_root or discover_project_root()
    if project_root is None:
        console.print(
            "[red]未找到小说项目。请先执行 `writer new <书名>` 创建项目，"
            "再 cd 进入项目目录后使用 `/init <故事梗概>`。[/red]"
        )
        return True

    # ``session.set_project_root`` 在绑定时已经 ``refresh_project_genre()``，
    # ``session.project_genre`` 即磁盘题材行的权威缓存。
    current_genre = session.project_genre

    console.print(f"[dim]当前题材: {current_genre}[/dim]")
    selected = prompt_genres(console, default=None)
    if not selected:
        selected = ["其他"]

    # 跨模块懒加载（与 flag 形式保持一致）。
    from writer.cli._init_backend import apply_genre_and_brief
    from writer.config import get_settings

    try:
        outcome = apply_genre_and_brief(
            project_root,
            genres=selected,
            brief=rest,
            settings=get_settings(),
        )
    except Exception as exc:  # noqa: BLE001 — 把任何 LLM / 写入错误转成 UI 提示
        console.print(f"[red]初始化失败：{exc}[/red]")
        return True

    session.refresh_project_genre()

    console.print(f"[green]已选择题材：[/green]{', '.join(outcome.selected_genres) or '其他'}")
    if outcome.created_files:
        console.print(f"[green]新增文件：[/green]{len(outcome.created_files)} 个")
        for path in outcome.created_files:
            console.print(f"  - {path}")
    if outcome.genre_line_changed:
        console.print("[green]已更新 AGENT.md 题材行[/green]")
    console.print(
        f"[green]已写入 创意/核心创意.md[/green]"
        f"（来源: {outcome.brief_source}）"
    )
    console.print("[green]已更新 AGENT.md 基本要求[/green]")
    return True


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

    # Brief 形式（``/init <故事梗概>``）：先于引擎分发拦截，做多选题材 +
    # 补脚手架 + 写 brief。判定条件：开头 ``/init`` 且看起来像故事概要
    # （``looks_like_creative_brief``）。helper 返回 False（短 token /
    # 项目名形式）时落给引擎。
    # 不再支持 ``/init --name X --dir Y`` flag 形式 —— 创建项目请用 CLI
    # 子命令 ``writer new <书名>``（per 2026-07-14）。
    if text.startswith("/init ") and _try_handle_repl_init_brief(text, session):
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

    委托给 :meth:`EngineSession.run_turn`，由 session 构造
    :class:`EngineContext` 并调用 :meth:`Engine.run`。若上一轮产出了
    ``Interrupt`` 事件，则把待回答的 prompt 与用户输入拼好后喂给
    引擎。
    """
    session.refresh_project_state()

    async for event in session.run_turn(user_input):
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


def _warn_deterministic_prose_client(session: EngineSession) -> None:
    """REPL 启动时检测 prose_client 是否为 deterministic 模式。

    Per 2026-07-14：``plan_chapter`` 在 deterministic 模式下严格拒绝
    (raise RuntimeError) 以强制用户配 ``WRITER_API_KEY``。为避免用户
    跑到命令才发现,REPL 启动时打印一次性软警告。

    Real 模式下静默。``prose_client`` 为 ``None`` 时也静默
    （生产装配始终填充字段,``None`` 通常是手写 stub 的测试 stub,
    不必用户面对噪音）。
    """
    engine = session.engine
    if engine is None:
        return
    prose_client = engine.deps.prose_client
    if prose_client is None:
        return
    if getattr(prose_client, "name", "") != "deterministic":
        return
    console.print(
        "[yellow]⚠ /创作 /审核 工作流需要真实 LLM；当前未配置 WRITER_API_KEY，"
        "调用将失败。请设置后重启 REPL。[/yellow]"
    )


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
    # Per 2026-07-14:REPL 启动时检查 prose_client 名,deterministic 模式
    # 软警告用户 ``/创作`` / ``/审核`` 将不可用。不阻断 REPL 启动。
    _warn_deterministic_prose_client(engine_session)
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
    assert engine_session.engine is not None  # __post_init__ 保障
    directive_registry = engine_session.engine.deps.directive_registry

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
