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
    "草稿",
    "大纲",
    "人物",
    "世界观",
    "备忘",
    "正文",
]

EXPECTED_FILES = [
    "AGENT.md",
    "README.md",
    "大纲/一句话创意.md",
    "大纲/分卷规划.md",
    "人物/主要人物.md",
    "世界观/世界观设定.md",
    "备忘/待办.md",
]

HISTORY_FILES = [
    "史实/年表.md",
    "史实/人物.md",
    "史实/事件.md",
    "史实/考证.md",
]

XUANHUAN_FILES = [
    "伏笔/伏笔表.md",
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

    premise = (workspace.root / "大纲" / "一句话创意.md").read_text(encoding="utf-8")
    assert premise == "# 一句话创意\n\n"

    volume_plan = (workspace.root / "大纲" / "分卷规划.md").read_text(encoding="utf-8")
    assert volume_plan == "# 分卷规划\n\n"

    main_chars = (workspace.root / "人物" / "主要人物.md").read_text(encoding="utf-8")
    assert main_chars == "# 主要人物\n\n"

    setting = (workspace.root / "世界观" / "世界观设定.md").read_text(encoding="utf-8")
    assert setting == "# 世界观设定\n\n"

    todo = (workspace.root / "备忘" / "待办.md").read_text(encoding="utf-8")
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


# ---------------------------------------------------------------------------
# fea-agent-mirror: agent mirror via _seed_agents
# ---------------------------------------------------------------------------


def test_create_new_workspace_seeds_all_four_agents(tmp_path: Path) -> None:
    """``writer new`` mirrors the 4 shipped agent .md files to .writer/agents/."""

    from writer.project.workspace import create_new_workspace

    workspace = create_new_workspace("mirror_test", tmp_path, genres=["历史"])
    agents_dir = workspace.root / ".writer" / "agents"
    mirrored = sorted(p.name for p in agents_dir.iterdir() if p.suffix == ".md")
    assert mirrored == ["other.md", "历史.md", "玄幻.md", "言情.md"]


def test_create_workspace_low_level_does_not_seed_agents(tmp_path: Path) -> None:
    """The low-level ``create_workspace`` API does NOT seed agents.

    Even with ``with_writer_meta=True`` the agents/ directory is
    created (so project-level overrides can be added later) but no
    .md files are mirrored. This preserves back-compat for the
    ``create_workspace`` API used by /init and the test fixtures.
    """

    from writer.project.workspace import create_workspace

    workspace = create_workspace(
        "low_level", tmp_path, with_writer_meta=True
    )
    agents_dir = workspace.root / ".writer" / "agents"
    assert agents_dir.is_dir(), "agents dir should be created"
    contents = [p.name for p in agents_dir.iterdir()]
    assert contents == [], (
        "low-level create_workspace must not seed agents, got: "
        f"{contents}"
    )


def test_mirrored_agent_file_has_valid_frontmatter(tmp_path: Path) -> None:
    """The mirrored ``历史.md`` has a parseable YAML frontmatter + non-empty body."""

    from writer.agents import parse_agent_file
    from writer.project.workspace import create_new_workspace

    workspace = create_new_workspace("frontmatter_test", tmp_path, genres=["历史"])
    history_path = workspace.root / ".writer" / "agents" / "历史.md"
    assert history_path.is_file()

    agent = parse_agent_file(history_path)
    assert agent.name == "history"
    assert agent.genre == "历史"
    assert len(agent.body.strip()) > 50


def test_mirror_does_not_overwrite_user_modified_agents(tmp_path: Path) -> None:
    """A pre-existing user-edited agent file is NOT overwritten on re-init.

    Per the spec: ``writer new`` mirrors shipped source only when the
    target file does not exist. A user-modified .md stays intact.
    """

    from writer.project.workspace import create_new_workspace

    # First init — creates the 4 mirrored files
    workspace = create_new_workspace("no_overwrite", tmp_path, genres=["other"])
    history_path = workspace.root / ".writer" / "agents" / "历史.md"

    # User edits the file
    history_path.write_text(
        "---\nname: history\ndescription: USER MODIFIED — very long description here to satisfy the validator\n"
        "genre: 历史\ntools: []\n---\n\n# USER BODY\n",
        encoding="utf-8",
    )

    # Re-run with force=True (which should NOT touch existing files)
    create_new_workspace(
        "no_overwrite", tmp_path, genres=["other"], force=True
    )
    text = history_path.read_text(encoding="utf-8")
    assert "USER MODIFIED" in text
    assert "USER BODY" in text


# ---------------------------------------------------------------------------
# apply_genre_scaffolding — public additive API for REPL ``/init <brief>``
# ---------------------------------------------------------------------------


def test_apply_genre_scaffolding_handles_multiple_genres(tmp_path: Path) -> None:
    """多题材下，所有白名单题材的脚手架都应创建。"""

    from writer.project.workspace import apply_genre_scaffolding

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n\n", encoding="utf-8")

    created = apply_genre_scaffolding(project, ["历史", "玄幻"])

    relative = sorted(p.relative_to(project).as_posix() for p in created)
    assert relative == sorted(
        HISTORY_FILES + XUANHUAN_FILES
    ), f"expected history + xuanhuan scaffolds, got {relative}"


def test_apply_genre_scaffolding_skips_existing_files(tmp_path: Path) -> None:
    """已存在的文件不被覆盖；返回列表只包含实际新建路径。"""

    from writer.project.workspace import apply_genre_scaffolding

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n\n", encoding="utf-8")

    # 第一次跑：创建所有历史文件
    first = apply_genre_scaffolding(project, ["历史"])
    assert len(first) == 4
    # 用户编辑其中一个
    user_note = "# 用户备注：不得覆盖\n"
    (project / "史实" / "年表.md").write_text(user_note, encoding="utf-8")

    # 第二次跑（题材切换 + 玄幻新增）：历史文件原样保留
    second = apply_genre_scaffolding(project, ["历史", "玄幻"])

    relative = sorted(p.relative_to(project).as_posix() for p in second)
    assert relative == sorted(XUANHUAN_FILES)
    # 历史文件未被改写
    assert (project / "史实" / "年表.md").read_text(encoding="utf-8") == user_note


def test_apply_genre_scaffolding_unknown_genre_is_noop(tmp_path: Path) -> None:
    """``other`` 与未知值不创建任何文件。"""

    from writer.project.workspace import apply_genre_scaffolding

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n\n", encoding="utf-8")

    assert apply_genre_scaffolding(project, ["other"]) == []
    assert apply_genre_scaffolding(project, [""]) == []
    assert apply_genre_scaffolding(project, ["科幻", "悬疑"]) == []
    # 即便混入白名单题材，未知值仍按白名单处理
    created = apply_genre_scaffolding(project, ["未知", "历史"])
    relative = sorted(p.relative_to(project).as_posix() for p in created)
    assert relative == sorted(HISTORY_FILES)
