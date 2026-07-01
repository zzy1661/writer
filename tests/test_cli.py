from typer.testing import CliRunner

from writer.cli.main import app


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
