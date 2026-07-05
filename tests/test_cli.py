from pathlib import Path

from typer.testing import CliRunner

from writer.cli.main import (
    EXIT_COMMANDS,
    HELP_COMMANDS,
    NO_HISTORY,
    REPL_COMMANDS,
    REPL_PROMPT,
    app,
    build_prompt_session,
    handle_repl_input,
)

runner = CliRunner()


def test_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0
    assert "writer-agent 0.1.0" in result.stdout


def test_outline() -> None:
    result = runner.invoke(app, ["outline", "废土少年继承一座会说话的图书馆"])

    assert result.exit_code == 0
    assert "废土少年继承一座会说话的图书馆" in result.stdout
    assert "第一幕" in result.stdout


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
    assert "/写" in result.stdout
    # 自然语言输入被 agent engine 接走，进入 answer_directly 终止分支
    assert "[engine] 分析输入" in result.stdout
    assert "帮我继续写下一章" in result.stdout
    assert "✓ answered" in result.stdout


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


def test_repl_command_aliases_present() -> None:
    """Every documented REPL command should be reachable via its slash form."""
    command_names = {cmd for cmd, _ in REPL_COMMANDS}
    assert {"/init", "/大纲", "/目录", "/写", "/续写", "/改", "/审核", "/状态", "/帮助", "/退出"} <= command_names
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
