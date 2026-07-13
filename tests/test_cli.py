import asyncio
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from rich.console import Console
from typer.testing import CliRunner

from writer.cli import main as cli_main
from writer.cli.main import (
    EXIT_COMMANDS,
    HELP_COMMANDS,
    NO_HISTORY,
    REPL_COMMANDS,
    REPL_PROMPT,
    _read_line,
    _run_engine,
    app,
    build_prompt_session,
    handle_repl_input,
)
from writer.engine.events import Done, ErrorEvent, Interrupt, ToolCall, ToolResult
from writer.session import EngineSession

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "writer-agent 0.1.0" in result.stdout


def test_repl_starts_with_welcome_page() -> None:
    result = runner.invoke(app, input="/退出\n")

    assert result.exit_code == 0
    assert "Writer Agent" in result.stdout
    assert "v0.1.0" in result.stdout
    assert "长篇小说写作控制台已启动" in result.stdout
    assert REPL_PROMPT.strip() in result.stdout
    assert "已退出 writer" in result.stdout


def test_repl_handles_help_and_user_input() -> None:
    result = runner.invoke(app, input="/帮助\n帮我继续写下一章\n/退出\n")

    assert result.exit_code == 0
    assert "可用命令" in result.stdout
    assert "/创作" in result.stdout
    # 自然语言输入被 agent engine 接走:出现 engine 分析日志 + 任意 Done 终止符
    # (LLM router 可能路由为 answer_directly / start_workflow / call_tool,
    # 任意一种都会渲染 ✓ <reason>，无需锁定具体分支)
    assert "[engine] 分析输入" in result.stdout
    assert "帮我继续写下一章" in result.stdout
    assert "✓ " in result.stdout


def test_handle_repl_input_returns_false_on_exit() -> None:
    from writer.session import EngineSession

    session = EngineSession()
    assert handle_repl_input("/退出", session) is False
    assert handle_repl_input("/q", session) is False
    assert handle_repl_input("exit", session) is False


def test_handle_repl_input_keeps_loop_on_empty() -> None:
    from writer.session import EngineSession

    session = EngineSession()
    assert handle_repl_input("", session) is True
    assert handle_repl_input("   ", session) is True


def test_handle_repl_input_unknown_slash_command() -> None:
    from writer.session import EngineSession

    session = EngineSession()
    assert handle_repl_input("/init", session) is True


def test_build_prompt_session_writes_history_file(tmp_path: Path) -> None:
    history_file = tmp_path / "writer" / "history"

    session = build_prompt_session(history_file=history_file)

    assert session.history is not None
    assert history_file.parent.is_dir()


def test_build_prompt_session_supports_no_history() -> None:
    from prompt_toolkit.history import FileHistory

    session = build_prompt_session(history_file=NO_HISTORY)

    assert not isinstance(session.history, FileHistory)


def test_repl_completer_filters_by_prefix() -> None:
    """Slash commands should narrow as the user types (e.g. /ini → /init only)."""
    from prompt_toolkit.document import Document

    session = build_prompt_session(history_file=NO_HISTORY)
    assert session.completer is not None

    def completions_for(text: str) -> list[str]:
        doc = Document(text, len(text))
        return [c.text for c in session.completer.get_completions(doc, None)]

    all_slash = completions_for("/")
    assert "/init" in all_slash
    assert len(all_slash) >= len(REPL_COMMANDS)

    assert completions_for("/ini") == ["/init"]
    assert completions_for("/大") == ["/大纲"]


def test_repl_completer_replaces_partial_command_not_double_slash() -> None:
    """Selecting a completion must replace the typed prefix, not append after '/'."""
    from prompt_toolkit.document import Document

    session = build_prompt_session(history_file=NO_HISTORY)
    assert session.completer is not None

    doc = Document("/", 1)
    completion = next(session.completer.get_completions(doc, None))
    assert completion.text == "/init"
    assert completion.start_position == -1

    doc_ini = Document("/ini", 4)
    completion_ini = next(session.completer.get_completions(doc_ini, None))
    assert completion_ini.text == "/init"
    assert completion_ini.start_position == -4


def test_repl_command_aliases_present() -> None:
    """Every documented REPL command should be reachable via its slash form."""
    command_names = {cmd for cmd, _ in REPL_COMMANDS}
    assert {"/init", "/大纲", "/目录", "/创作", "/审核", "/状态", "/帮助", "/退出"} <= command_names
    assert "/退出" in EXIT_COMMANDS
    assert "/帮助" in HELP_COMMANDS


# ---------------------------------------------------------------------------
# EngineSession integration (per add-engine-session change)
# ---------------------------------------------------------------------------


def test_repl_session_survives_across_lines() -> None:
    """Multiple /状态 calls in one REPL run print the same session_id."""
    result = runner.invoke(app, input="/状态\n/状态\n/退出\n")

    assert result.exit_code == 0
    # Both /状态 outputs should show the same UUID
    import re

    uuids = re.findall(
        r"session=([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})",
        result.stdout,
    )
    assert len(uuids) == 2, f"expected 2 /状态 outputs, got: {uuids}"
    assert uuids[0] == uuids[1], f"session_id changed across turns: {uuids}"


def test_repl_exit_command_terminates_session() -> None:
    """`/退出` returns False from handle_repl_input → REPL loop ends."""
    from writer.session import EngineSession

    session = EngineSession()
    assert handle_repl_input("/退出", session) is False


def test_repl_pending_interrupt_visible_in_next_turn() -> None:
    """When an Interrupt event is emitted, the next turn's input is composed."""
    from writer.engine.events import Interrupt
    from writer.session import EngineSession, compose_pending_input

    # Simulate engine emitting Interrupt then Done across two turns
    session = EngineSession()
    intr = Interrupt(type="text", prompt="你想修改哪一段？")
    session.set_pending_interrupt(intr)

    # Simulate the REPL driver's behavior at start of next turn
    next_input = compose_pending_input("修第2段", session.pending_interrupt)

    assert "[pending] 你想修改哪一段？" in next_input
    assert "[answer] 修第2段" in next_input

    # Simulate end-of-turn: Done clears the pending interrupt
    session.record_turn("修第2段", "answered")  # type: ignore[arg-type]
    session.clear_pending_interrupt()
    assert session.pending_interrupt is None


# ---------------------------------------------------------------------------
# doctor subcommand + _run_engine event rendering + REPL EOF
# ---------------------------------------------------------------------------


def test_doctor_command_renders_settings_table() -> None:
    """``writer doctor`` prints a table with model, base_url, api-key, temperature."""
    result = runner.invoke(app, ["doctor"])

    assert result.exit_code == 0
    assert "writer-agent doctor" in result.stdout
    assert "模型" in result.stdout
    assert "Base URL" in result.stdout
    assert "API Key" in result.stdout
    assert "Temperature" in result.stdout
    # The default temperature is 0.7 (Settings default).
    assert "0.7" in result.stdout
    # API Key column is either 已配置 or 未配置 depending on env.
    assert ("已配置" in result.stdout) or ("未配置" in result.stdout)


def test_run_engine_renders_tool_call_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``ToolCall`` event is rendered with the yellow ⚙ marker."""

    async def fake_run_engine(ctx: object, deps: object) -> object:  # async iterator
        yield ToolCall(name="safe_read_file", arguments={"path": "x"})
        yield Done(reason="tool_completed")

    monkeypatch.setattr(cli_main, "run_engine", fake_run_engine)

    session = EngineSession()
    buf = Console(record=True, force_terminal=False)

    asyncio.run(_run_engine("anything", session, buf))

    text = buf.export_text()
    assert "⚙" in text
    assert "safe_read_file" in text


def test_run_engine_renders_tool_result_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """A ``ToolResult`` event is rendered with the green ✓ marker."""

    async def fake_run_engine(ctx: object, deps: object) -> object:
        yield ToolResult(name="safe_read_file", output="file contents")
        yield Done(reason="tool_completed")

    monkeypatch.setattr(cli_main, "run_engine", fake_run_engine)

    session = EngineSession()
    buf = Console(record=True, force_terminal=False)

    asyncio.run(_run_engine("anything", session, buf))

    text = buf.export_text()
    assert "✓" in text
    assert "safe_read_file" in text
    assert "file contents" in text


def test_run_engine_binds_project_root_from_done_payload(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A successful /init payload should bind the REPL session to the project."""

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("state: S1", encoding="utf-8")

    async def fake_run_engine(ctx: object, deps: object) -> object:
        yield Done(
            reason="answered",
            payload={"project_root": str(project), "project_state": "S1"},
        )

    monkeypatch.setattr(cli_main, "run_engine", fake_run_engine)

    session = EngineSession()
    buf = Console(record=True, force_terminal=False)

    asyncio.run(_run_engine("/init novel", session, buf))

    assert session.project_root == project
    assert session.project_state == "S1"


def test_run_engine_renders_interrupt_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ``Interrupt`` event stashes a prompt on the session and renders ? + prompt."""

    async def fake_run_engine(ctx: object, deps: object) -> object:
        yield Interrupt(type="text", prompt="你想修改哪一段？")
        yield Done(reason="answered")

    monkeypatch.setattr(cli_main, "run_engine", fake_run_engine)

    session = EngineSession()
    buf = Console(record=True, force_terminal=False)

    asyncio.run(_run_engine("anything", session, buf))

    text = buf.export_text()
    assert "?" in text
    assert "你想修改哪一段？" in text
    # Interrupt cleared because Done came after it
    assert session.pending_interrupt is None


def test_run_engine_renders_error_event(monkeypatch: pytest.MonkeyPatch) -> None:
    """An ``ErrorEvent`` is rendered with the red ✗ marker."""

    async def fake_run_engine(ctx: object, deps: object) -> object:
        yield ErrorEvent(message="boom")
        yield Done(reason="aborted")

    monkeypatch.setattr(cli_main, "run_engine", fake_run_engine)

    session = EngineSession()
    buf = Console(record=True, force_terminal=False)

    asyncio.run(_run_engine("anything", session, buf))

    text = buf.export_text()
    assert "✗" in text
    assert "boom" in text


def test_run_engine_renders_project_state_on_aborted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A ``Done(aborted, payload={'project_state': ...})`` must surface the state.

    Per arch-optimizer M5 (2026-07-07): previously the payload's
    ``project_state`` was silently dropped — the user saw
    ``[green]✓ aborted[/green]`` but had no idea *why*. The fix
    renders the state (with optional description from
    ``STATE_DESCRIPTIONS``) on the line below.
    """

    async def fake_run_engine(ctx: object, deps: object) -> object:
        yield Done(
            reason="aborted",
            payload={
                "command": "/创作",
                "project_state": "S1",
                "error": "状态机拦截",
            },
        )

    monkeypatch.setattr(cli_main, "run_engine", fake_run_engine)

    session = EngineSession()
    buf = Console(record=True, force_terminal=False)

    asyncio.run(_run_engine("/创作 1.3", session, buf))

    text = buf.export_text()
    assert "当前状态: S1" in text


def test_read_line_uses_prompt_session_when_provided() -> None:
    """When a prompt_session is passed, _read_line delegates to session.prompt()."""
    mock_session = MagicMock()
    mock_session.prompt.return_value = "user typed this"

    result = _read_line(mock_session, "foo>")

    assert result == "user typed this"
    mock_session.prompt.assert_called_once_with("foo>")


def test_run_repl_handles_eof() -> None:
    """Empty stdin (EOF) exits the REPL cleanly with the green farewell."""
    result = runner.invoke(app, input="")

    assert result.exit_code == 0
    assert "已退出 writer" in result.stdout


# ---------------------------------------------------------------------------
# /init (only the brief 形式;flag 形式已于 2026-07-14 删除)
# ---------------------------------------------------------------------------


def test_repl_init_alone_falls_through_to_engine(tmp_path: Path) -> None:
    """Plain ``/init`` (no brief args) should fall through to the engine."""

    result = runner.invoke(app, input="/init\n/退出\n")

    assert result.exit_code == 0


def test_build_prompt_session_falls_back_when_home_is_unwritable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from writer.cli.main import NO_HISTORY, build_prompt_session

    monkeypatch.setenv("HOME", "/nonexistent-home-writer-test")
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)

    session = build_prompt_session()
    assert session is not None

    session_no_history = build_prompt_session(NO_HISTORY)
    assert session_no_history is not None


# ---------------------------------------------------------------------------
# REPL ``/init <brief>`` 简洁形式拦截（apply_genre_and_brief 后端接线）
# ---------------------------------------------------------------------------


def test_repl_init_brief_creates_scaffold_and_writes_brief(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``/init <故事梗概>`` 在已存在项目上：补脚手架 + 写 brief。"""

    from writer.cli.main import handle_repl_input
    from writer.session import EngineSession

    # 已有 S1 项目（``writer new`` 路径）
    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text(
        "# novel\n\n## 当前状态\n\n- state: S1\n- label: 初始化\n",
        encoding="utf-8",
    )
    # 显式把 session 绑定到项目（与 REPL 启动时的 ``set_project_root`` 等价）
    session = EngineSession()
    session.set_project_root(project)

    # 必须含 ``looks_like_creative_brief`` 识别的标点（``。`` 等）
    brief = (
        "林远穿越到了他写的游戏中。但他写的游戏是一个充满温馨故事的城市，"
        "然而他穿越到的这个世界是一个充满杀戮和罪恶的世界。"
    )
    assert handle_repl_input(f"/init {brief}", session) is True

    # 多选提示走 ``["其他"]`` 兜底（非 TTY）—— ``其他`` 是 ``other`` 别名，
    # :func:`format_genre_line` 过滤掉 → 无 ``题材:`` 行；brief 仍写入。
    assert (project / "创意" / "核心创意.md").is_file()
    agent_text = (project / "AGENT.md").read_text(encoding="utf-8")
    assert "## 基本要求" in agent_text


def test_repl_init_brief_aborts_when_no_project_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """没有项目根目录时，REPL 拦截并提示，不进引擎。"""

    from writer.cli.main import handle_repl_input
    from writer.session import EngineSession

    # cwd 切到没有任何项目的目录，session 没有 project_root
    monkeypatch.chdir(tmp_path)
    session = EngineSession()
    assert session.project_root is None

    brief = (
        "林远穿越到了他写的游戏中。但他写的游戏是一个充满温馨故事的城市，"
        "然而他穿越到的这个世界是一个充满杀戮和罪恶的世界。"
    )
    assert handle_repl_input(f"/init {brief}", session) is True
    # 不应创建任何项目目录
    assert not (tmp_path / "novel").exists()
    assert not (tmp_path / "创意").exists()


def test_repl_init_brief_helper_returns_false_for_non_brief(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """短 token（``looks_like_project_name`` 形态）应落给引擎处理。"""

    from writer.cli.main import _try_handle_repl_init_brief
    from writer.session import EngineSession

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text(
        "# novel\n\n## 当前状态\n\n- state: S1\n- label: 初始化\n",
        encoding="utf-8",
    )
    session = EngineSession()
    session.set_project_root(project)

    # ``双生`` 短 token，不是 creative brief —— 让既有 argv 解析路径处理
    assert _try_handle_repl_init_brief("/init 双生", session) is False
