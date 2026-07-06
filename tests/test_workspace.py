"""Unit tests for ``writer.project.workspace``.

Covers:
- ``create_workspace`` (directory creation, file templates, force flag)
- ``_normalize_name`` (whitespace stripping, space→dash, empty rejection)
- ``NovelWorkspace`` (frozen dataclass)
- Genre-aware scaffolding (fea-genre-aware-init Block 1)
"""

from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from writer.project.workspace import (
    _normalize_name,
    create_workspace,
)

EXPECTED_DIRS = [
    "manuscript",
    "outline",
    "characters",
    "world",
    "notes",
]

EXPECTED_FILES = [
    "AGENT.md",
    "README.md",
    "outline/premise.md",
    "outline/volume-plan.md",
    "characters/main.md",
    "world/setting.md",
    "notes/todo.md",
]

HISTORY_FILES = [
    "史实/年表.md",
    "史实/人物.md",
    "史实/事件.md",
    "史实/考证.md",
]

XUANHUAN_FILES = [
    "伏笔/foreshadow.md",
    "大纲/境界表.md",
]

ROMANCE_FILES = [
    "人设/男主.md",
    "人设/女主.md",
    "大纲/感情线时间轴.md",
]


def _relative(paths: list[Path], root: Path) -> set[str]:
    return {p.relative_to(root).as_posix() for p in paths}


def test_create_workspace_creates_expected_dirs_and_files(tmp_path: Path) -> None:
    workspace = create_workspace("我的小说", tmp_path)

    for directory in EXPECTED_DIRS:
        assert (workspace.root / directory).is_dir()

    for relative in EXPECTED_FILES:
        assert (workspace.root / relative).is_file()


def test_create_workspace_returns_paths_in_created_files(tmp_path: Path) -> None:
    workspace = create_workspace("我的小说", tmp_path)

    assert workspace.root.parent == tmp_path
    assert workspace.root.name == "我的小说"

    relative = {p.relative_to(workspace.root).as_posix() for p in workspace.created_files}
    assert relative == set(EXPECTED_FILES)


def test_create_workspace_normalizes_spaces_in_name(tmp_path: Path) -> None:
    workspace = create_workspace("My Novel", tmp_path)

    assert workspace.root.name == "My-Novel"
    assert workspace.root.is_dir()


def test_create_workspace_strips_whitespace_in_name(tmp_path: Path) -> None:
    workspace = create_workspace("  foo  ", tmp_path)

    assert workspace.root.name == "foo"


def test_create_workspace_file_contents_match_template(tmp_path: Path) -> None:
    workspace = create_workspace("测试项目", tmp_path)

    readme = (workspace.root / "README.md").read_text(encoding="utf-8")
    assert readme == "# 测试项目\n\n长篇小说项目工作区。\n"

    agent = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "state: S1" in agent

    premise = (workspace.root / "outline" / "premise.md").read_text(encoding="utf-8")
    assert premise == "# 一句话创意\n\n"

    volume_plan = (workspace.root / "outline" / "volume-plan.md").read_text(encoding="utf-8")
    assert volume_plan == "# 分卷规划\n\n"

    main_chars = (workspace.root / "characters" / "main.md").read_text(encoding="utf-8")
    assert main_chars == "# 主要人物\n\n"

    setting = (workspace.root / "world" / "setting.md").read_text(encoding="utf-8")
    assert setting == "# 世界观设定\n\n"

    todo = (workspace.root / "notes" / "todo.md").read_text(encoding="utf-8")
    assert todo == "# 待办\n\n"


def test_create_workspace_raises_when_dir_exists_without_force(tmp_path: Path) -> None:
    create_workspace("dup", tmp_path)

    with pytest.raises(FileExistsError, match="项目目录已存在"):
        create_workspace("dup", tmp_path)


def test_create_workspace_overwrites_existing_files_when_force(tmp_path: Path) -> None:
    workspace_first = create_workspace("dup", tmp_path)
    readme = workspace_first.root / "README.md"
    readme.write_text("stale content", encoding="utf-8")

    workspace_second = create_workspace("dup", tmp_path, force=True)

    assert workspace_second.root == workspace_first.root
    assert readme.read_text(encoding="utf-8") == "# dup\n\n长篇小说项目工作区。\n"
    relative = {p.relative_to(workspace_second.root).as_posix() for p in workspace_second.created_files}
    assert relative == set(EXPECTED_FILES)


def test_create_workspace_keeps_existing_files_when_not_force(tmp_path: Path) -> None:
    """With ``force=False``, the function refuses to touch an existing root.

    create_workspace either creates a brand new directory tree (all files
    reported in created_files) or raises FileExistsError. There is no
    intermediate state where the root exists without force and the function
    silently keeps stale files — that's what force=True is for.
    """
    first = create_workspace("dup", tmp_path)
    (first.root / "README.md").write_text("stale", encoding="utf-8")

    with pytest.raises(FileExistsError):
        create_workspace("dup", tmp_path)

    assert (first.root / "README.md").read_text(encoding="utf-8") == "stale"


def test_create_workspace_raises_value_error_on_empty_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="项目名称不能为空"):
        create_workspace("", tmp_path)


def test_create_workspace_raises_value_error_on_whitespace_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="项目名称不能为空"):
        create_workspace("   ", tmp_path)


def test_normalize_name_replaces_internal_spaces() -> None:
    assert _normalize_name("hello world") == "hello-world"
    assert _normalize_name("a  b  c") == "a--b--c"
    assert _normalize_name(" leading") == "leading"
    assert _normalize_name("trailing ") == "trailing"


def test_novel_workspace_is_frozen(tmp_path: Path) -> None:
    workspace = create_workspace("frozen-test", tmp_path)

    with pytest.raises(FrozenInstanceError):
        workspace.root = tmp_path / "other"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        workspace.created_files = []  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Genre-aware scaffolding (fea-genre-aware-init Block 1)
# ---------------------------------------------------------------------------


def test_create_workspace_history_genre_appends_history_dirs(tmp_path: Path) -> None:
    workspace = create_workspace("长安", tmp_path, genre="历史")

    for relative in HISTORY_FILES:
        assert (workspace.root / relative).is_file()
    for relative in EXPECTED_FILES:
        assert (workspace.root / relative).is_file()
    assert HISTORY_FILES[0] in _relative(workspace.created_files, workspace.root)


def test_create_workspace_xuanhuan_genre_appends_xuanhuan_dirs(tmp_path: Path) -> None:
    workspace = create_workspace("破界", tmp_path, genre="玄幻")

    for relative in XUANHUAN_FILES:
        assert (workspace.root / relative).is_file()
    assert not (workspace.root / "史实").exists()
    assert not (workspace.root / "人设").exists()


def test_create_workspace_romance_genre_appends_romance_dirs(tmp_path: Path) -> None:
    workspace = create_workspace("双生", tmp_path, genre="言情")

    for relative in ROMANCE_FILES:
        assert (workspace.root / relative).is_file()
    assert not (workspace.root / "史实").exists()
    assert not (workspace.root / "伏笔").exists()


def test_create_workspace_other_genre_is_backward_compatible(tmp_path: Path) -> None:
    workspace = create_workspace("杂项", tmp_path)

    relative = _relative(workspace.created_files, workspace.root)
    assert relative == set(EXPECTED_FILES)
    assert not (workspace.root / "史实").exists()
    assert not (workspace.root / "伏笔").exists()
    assert not (workspace.root / "人设").exists()


def test_create_workspace_unknown_genre_falls_back_to_other(tmp_path: Path) -> None:
    workspace = create_workspace("试验", tmp_path, genre="都市悬疑")

    relative = _relative(workspace.created_files, workspace.root)
    assert relative == set(EXPECTED_FILES)
    assert "史实" not in relative
    assert "伏笔" not in relative
    assert "人设" not in relative


def test_create_workspace_english_genre_aliases_resolve(tmp_path: Path) -> None:
    workspace_x = create_workspace("a1", tmp_path, genre="xuanhuan")
    workspace_r = create_workspace("b1", tmp_path, genre="romance")
    workspace_h = create_workspace("c1", tmp_path, genre="history")

    assert "大纲/境界表.md" in _relative(workspace_x.created_files, workspace_x.root)
    assert "人设/男主.md" in _relative(workspace_r.created_files, workspace_r.root)
    assert "史实/年表.md" in _relative(workspace_h.created_files, workspace_h.root)


def test_create_workspace_writes_genre_line_in_agent_md(tmp_path: Path) -> None:
    workspace = create_workspace("贞观", tmp_path, genre="历史")

    agent_text = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "题材: 历史" in agent_text
    assert "state: S1" in agent_text


def test_create_workspace_other_genre_has_no_ticaline_in_agent_md(tmp_path: Path) -> None:
    workspace = create_workspace("default", tmp_path)

    agent_text = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "state: S1" in agent_text
    assert "题材:" not in agent_text
