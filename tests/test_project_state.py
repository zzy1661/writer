from __future__ import annotations

from pathlib import Path

import pytest

from writer.project import (
    ProjectState,
    create_workspace,
    detect_state,
    discover_project_root,
    inspect_project,
    refresh_agent_file,
)


def test_detect_state_returns_s0_without_project() -> None:
    assert detect_state(None) == ProjectState.UNINITIALIZED


def test_detect_state_returns_s1_for_new_workspace(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)

    assert detect_state(workspace.root) == ProjectState.INITIALIZED


def test_detect_state_returns_s2_after_outline_file(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    (workspace.root / "大纲" / "大纲.md").write_text("大纲内容", encoding="utf-8")

    assert detect_state(workspace.root) == ProjectState.HAS_OUTLINE


def test_detect_state_returns_s3_after_toc_file(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    (workspace.root / "大纲" / "大纲.md").write_text("大纲内容", encoding="utf-8")
    (workspace.root / "大纲" / "章节目录.md").write_text("第一章", encoding="utf-8")

    assert detect_state(workspace.root) == ProjectState.HAS_TOC


def test_detect_state_returns_s4_after_manuscript(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    (workspace.root / "草稿" / "chapter-01.md").write_text(
        "正文",
        encoding="utf-8",
    )

    assert detect_state(workspace.root) == ProjectState.WRITING


def test_inspect_project_reports_chapter_count_and_outline(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    outline = workspace.root / "大纲" / "大纲.md"
    outline.write_text("大纲内容", encoding="utf-8")
    (workspace.root / "草稿" / "chapter-01.md").write_text(
        "正文",
        encoding="utf-8",
    )

    snapshot = inspect_project(workspace.root)

    assert snapshot.state == ProjectState.WRITING
    assert snapshot.chapter_count == 1
    assert snapshot.outline_path == outline


def test_refresh_agent_file_writes_detected_state(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    (workspace.root / "大纲" / "大纲.md").write_text("大纲内容", encoding="utf-8")

    refresh_agent_file(workspace.root)

    agent = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "state: S2" in agent


def test_discover_project_root_returns_cwd_when_agent_exists(tmp_path: Path) -> None:
    workspace = create_workspace("根目录项目", tmp_path)

    assert discover_project_root(workspace.root) == workspace.root.resolve()


def test_discover_project_root_returns_single_child_project(tmp_path: Path) -> None:
    workspace = create_workspace("子目录项目", tmp_path)

    assert discover_project_root(tmp_path) == workspace.root.resolve()


def test_discover_project_root_returns_none_when_cwd_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken_cwd() -> Path:
        msg = "No such file or directory"
        raise FileNotFoundError(2, msg)

    monkeypatch.setattr(Path, "cwd", classmethod(lambda cls: broken_cwd()))

    assert discover_project_root() is None


def test_discover_project_root_returns_none_when_ambiguous(tmp_path: Path) -> None:
    create_workspace("项目A", tmp_path)
    create_workspace("项目B", tmp_path)

    assert discover_project_root(tmp_path) is None


# ---------------------------------------------------------------------------
# update_agent_genre_line — local patch for REPL ``/init <brief>``
# ---------------------------------------------------------------------------


def test_update_agent_genre_line_adds_when_missing(tmp_path: Path) -> None:
    """AGENT.md 缺少 ``题材:`` 行时，在首个 ``## ...`` 标题前插入。"""

    from writer.project.state import update_agent_genre_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    # 先手工移除 ``题材:`` 行
    text = agent.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines(keepends=True) if "题材:" not in line]
    agent.write_text("".join(lines), encoding="utf-8")

    changed = update_agent_genre_line(agent, ["玄幻"])

    assert changed is True
    new_text = agent.read_text(encoding="utf-8")
    assert "- 题材: 玄幻" in new_text


def test_update_agent_genre_line_replaces_existing(tmp_path: Path) -> None:
    """AGENT.md 已有 ``题材: 历史`` 时改为 ``题材: 玄幻``。"""

    from writer.project.state import update_agent_genre_line

    workspace = create_workspace("novel", tmp_path, genre="历史")
    agent = workspace.root / "AGENT.md"
    assert "题材: 历史" in agent.read_text(encoding="utf-8")

    changed = update_agent_genre_line(agent, ["玄幻"])

    assert changed is True
    new_text = agent.read_text(encoding="utf-8")
    assert "题材: 玄幻" in new_text
    assert "题材: 历史" not in new_text


def test_update_agent_genre_line_removes_for_other(tmp_path: Path) -> None:
    """``format_genre_line`` 返回 ``None``（全 ``other``）时移除 ``题材:`` 行。"""

    from writer.project.state import update_agent_genre_line

    workspace = create_workspace("novel", tmp_path, genre="历史")
    agent = workspace.root / "AGENT.md"

    changed = update_agent_genre_line(agent, ["other"])

    assert changed is True
    new_text = agent.read_text(encoding="utf-8")
    assert "题材:" not in new_text


def test_update_agent_genre_line_preserves_basic_requirements(tmp_path: Path) -> None:
    """``## 基本要求`` 段被 :func:`append_agent_requirements` 追加后，\
    本函数更新题材行不应破坏它。"""

    from writer.project.state import (
        append_agent_requirements,
        update_agent_genre_line,
    )

    workspace = create_workspace("novel", tmp_path, genre="历史")
    agent = workspace.root / "AGENT.md"
    append_agent_requirements(agent, "风格: 轻松\n篇幅: 30 万字")

    update_agent_genre_line(agent, ["玄幻"])

    text = agent.read_text(encoding="utf-8")
    assert "## 基本要求" in text
    assert "风格: 轻松" in text
    assert "篇幅: 30 万字" in text
    assert "- 题材: 玄幻" in text


def test_update_agent_genre_line_noop_when_unchanged(tmp_path: Path) -> None:
    """相同 ``题材:`` 值再调用应返回 ``False``（no-op）。"""

    from writer.project.state import update_agent_genre_line

    workspace = create_workspace("novel", tmp_path, genre="历史")
    agent = workspace.root / "AGENT.md"

    assert update_agent_genre_line(agent, ["历史"]) is False
