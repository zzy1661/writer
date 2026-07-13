"""Tests for ``writer new`` and workspace scaffolding."""

from __future__ import annotations

from pathlib import Path

from typer.testing import CliRunner

from writer.cli.main import app
from writer.project import create_new_workspace, normalize_genres

runner = CliRunner()


def test_create_new_workspace_scaffold(tmp_path: Path) -> None:
    workspace = create_new_workspace("新书", tmp_path, genres=["历史", "言情"])

    assert (workspace.root / "创意").is_dir()
    assert (workspace.root / "创意" / "简介.md").is_file()
    assert (workspace.root / ".writer" / "config").is_file()
    assert (workspace.root / ".writer" / "skills").is_dir()
    assert (workspace.root / ".writer" / "agents").is_dir()
    assert (workspace.root / "史实" / "年表.md").is_file()
    agent = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "题材: 历史, 言情" in agent


def test_new_command_with_genre_flags(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("WRITER_API_KEY", "")
    result = runner.invoke(
        app,
        ["new", "我的新书", "--dir", str(tmp_path), "-g", "玄幻", "-g", "科幻"],
    )

    assert result.exit_code == 0
    root = tmp_path / "我的新书"
    assert (root / ".writer" / "config").is_file()
    assert (root / "创意").is_dir()
    assert "已创建新书项目" in result.stdout


def test_normalize_genres_dedupes_and_maps_aliases() -> None:
    assert normalize_genres(["历史", "history", "言情"]) == ["历史", "言情"]
