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
    assert handle_repl_input("/退出") is False
    assert handle_repl_input("/q") is False
    assert handle_repl_input("exit") is False


def test_handle_repl_input_keeps_loop_on_empty() -> None:
    assert handle_repl_input("") is True
    assert handle_repl_input("   ") is True


def test_handle_repl_input_unknown_slash_command() -> None:
    assert handle_repl_input("/init") is True


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