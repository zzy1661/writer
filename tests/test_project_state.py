from __future__ import annotations

from pathlib import Path

from writer.project import (
    ProjectState,
    create_workspace,
    detect_state,
    inspect_project,
    refresh_agent_file,
    validate_command_available,
)


def test_detect_state_returns_s0_without_project() -> None:
    assert detect_state(None) == ProjectState.UNINITIALIZED


def test_detect_state_returns_s1_for_new_workspace(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)

    assert detect_state(workspace.root) == ProjectState.INITIALIZED


def test_detect_state_returns_s2_after_outline_file(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    (workspace.root / "outline" / "大纲.md").write_text("大纲内容", encoding="utf-8")

    assert detect_state(workspace.root) == ProjectState.HAS_OUTLINE


def test_detect_state_returns_s3_after_toc_file(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    (workspace.root / "outline" / "大纲.md").write_text("大纲内容", encoding="utf-8")
    (workspace.root / "outline" / "toc.md").write_text("第一章", encoding="utf-8")

    assert detect_state(workspace.root) == ProjectState.HAS_TOC


def test_detect_state_returns_s4_after_manuscript(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    (workspace.root / "manuscript" / "chapter-01.md").write_text(
        "正文",
        encoding="utf-8",
    )

    assert detect_state(workspace.root) == ProjectState.WRITING


def test_inspect_project_reports_chapter_count_and_outline(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    outline = workspace.root / "outline" / "大纲.md"
    outline.write_text("大纲内容", encoding="utf-8")
    (workspace.root / "manuscript" / "chapter-01.md").write_text(
        "正文",
        encoding="utf-8",
    )

    snapshot = inspect_project(workspace.root)

    assert snapshot.state == ProjectState.WRITING
    assert snapshot.chapter_count == 1
    assert snapshot.outline_path == outline


def test_refresh_agent_file_writes_detected_state(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)
    (workspace.root / "outline" / "大纲.md").write_text("大纲内容", encoding="utf-8")

    refresh_agent_file(workspace.root)

    agent = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "state: S2" in agent


def test_validate_command_blocks_write_in_s0() -> None:
    check = validate_command_available("/创作", None, "S0")

    assert check.ok is False
    assert check.state == ProjectState.UNINITIALIZED
    assert "请先生成章节目录" in check.reason


def test_validate_command_allows_readonly_commands_after_init(tmp_path: Path) -> None:
    workspace = create_workspace("状态测试", tmp_path)

    check = validate_command_available("/查看", workspace.root)

    assert check.ok is True
    assert check.state == ProjectState.INITIALIZED
