"""Unit tests for ``writer.project.workspace``.

Covers:
- ``create_workspace`` (directory creation, file templates, force flag)
- ``_normalize_name`` (whitespace stripping, space→dash, empty rejection)
- ``NovelWorkspace`` (frozen dataclass)
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
    "README.md",
    "outline/premise.md",
    "outline/volume-plan.md",
    "characters/main.md",
    "world/setting.md",
    "notes/todo.md",
]


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
    # All template files should be re-created and reported
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

    # The stale README was preserved because we never made it past the guard.
    assert (first.root / "README.md").read_text(encoding="utf-8") == "stale"


def test_create_workspace_raises_value_error_on_empty_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="项目名称不能为空"):
        create_workspace("", tmp_path)


def test_create_workspace_raises_value_error_on_whitespace_name(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="项目名称不能为空"):
        create_workspace("   ", tmp_path)


def test_normalize_name_replaces_internal_spaces() -> None:
    assert _normalize_name("hello world") == "hello-world"
    # Every space becomes a dash — consecutive spaces are preserved as consecutive dashes.
    assert _normalize_name("a  b  c") == "a--b--c"
    assert _normalize_name(" leading") == "leading"
    assert _normalize_name("trailing ") == "trailing"


def test_novel_workspace_is_frozen(tmp_path: Path) -> None:
    workspace = create_workspace("frozen-test", tmp_path)

    with pytest.raises(FrozenInstanceError):
        workspace.root = tmp_path / "other"  # type: ignore[misc]

    with pytest.raises(FrozenInstanceError):
        workspace.created_files = []  # type: ignore[misc]
