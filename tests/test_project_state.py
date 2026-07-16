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


# ---------------------------------------------------------------------------
# 架构方法: AGENT.md 元数据契约（per 2026-07-16）
# ---------------------------------------------------------------------------


def test_render_agent_file_default_architecture_method_is_snowflake() -> None:
    """``render_agent_file`` 默认写 ``架构方法: 雪花法`` 行（per 2026-07-16）。"""

    from writer.project.state import render_agent_file

    text = render_agent_file("测试项目", ProjectState.INITIALIZED)
    assert "- 架构方法: 雪花法" in text


def test_render_agent_file_custom_architecture_method() -> None:
    """显式传入 ``architecture_method`` 时,AGENT.md 写入该值。"""

    from writer.project.state import render_agent_file

    text = render_agent_file(
        "测试项目",
        ProjectState.INITIALIZED,
        genre="玄幻",
        architecture_method="三步八段式",
    )
    assert "- 题材: 玄幻" in text
    assert "- 架构方法: 三步八段式" in text


def test_create_workspace_defaults_to_snowflake(tmp_path: Path) -> None:
    """新建项目 AGENT.md 默认含 ``架构方法: 雪花法``。"""

    workspace = create_workspace("novel", tmp_path)
    text = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "- 架构方法: 雪花法" in text


def test_create_workspace_accepts_custom_architecture_method(tmp_path: Path) -> None:
    """``create_workspace(..., architecture_method=...)`` 写入对应 AGENT.md。"""

    workspace = create_workspace(
        "novel",
        tmp_path,
        architecture_method="人物弧光架构",
    )
    text = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "- 架构方法: 人物弧光架构" in text


def test_read_architecture_method_falls_back_to_snowflake(tmp_path: Path) -> None:
    """AGENT.md 缺失或没有 ``架构方法:`` 行时,回退 ``雪花法``。"""

    from writer.project.state import (
        DEFAULT_ARCHITECTURE_METHOD,
        read_architecture_method_from_agent,
    )

    # 文件不存在
    missing = tmp_path / "no_agent.md"
    assert read_architecture_method_from_agent(missing) == DEFAULT_ARCHITECTURE_METHOD

    # 文件存在但没该行
    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    original = agent.read_text(encoding="utf-8")
    # 手动剥离 ``架构方法:`` 行
    stripped = "\n".join(
        line for line in original.splitlines() if not line.startswith("- 架构方法:")
    )
    agent.write_text(stripped, encoding="utf-8")
    assert read_architecture_method_from_agent(agent) == DEFAULT_ARCHITECTURE_METHOD


def test_read_architecture_method_parses_bare_and_list_forms(tmp_path: Path) -> None:
    """``架构方法:`` 行兼容 ``- 题材:`` 同样的 list 前缀规则。"""

    from writer.project.state import read_architecture_method_from_agent

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"

    # bare 形式（手写）
    original = agent.read_text(encoding="utf-8")
    text = original.replace("- 架构方法: 雪花法", "架构方法: 三幕结构")
    agent.write_text(text, encoding="utf-8")
    assert read_architecture_method_from_agent(agent) == "三幕结构"

    # - list 前缀形式
    text = original.replace("- 架构方法: 雪花法", "- 架构方法: 英雄之旅")
    agent.write_text(text, encoding="utf-8")
    assert read_architecture_method_from_agent(agent) == "英雄之旅"

    # * list 前缀形式
    text = original.replace("- 架构方法: 雪花法", "* 架构方法: 布莱克节拍表")
    agent.write_text(text, encoding="utf-8")
    assert read_architecture_method_from_agent(agent) == "布莱克节拍表"


def test_update_agent_architecture_method_line_inserts_when_missing(
    tmp_path: Path,
) -> None:
    """AGENT.md 没有该行时,插入到第一个 ``## ...`` 二级标题之前。"""

    from writer.project.state import update_agent_architecture_method_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    agent.write_text(
        "# 旧项目\n\n## 目录约定\n\n- 大纲/\n",
        encoding="utf-8",
    )

    changed = update_agent_architecture_method_line(agent, "三步八段式")

    assert changed is True
    text = agent.read_text(encoding="utf-8")
    assert "- 架构方法: 三步八段式" in text
    # 保留其他内容
    assert "# 旧项目" in text
    assert "## 目录约定" in text


def test_update_agent_architecture_method_line_replaces_existing(
    tmp_path: Path,
) -> None:
    """AGENT.md 已含该行时,就地替换而非新增第二条。"""

    from writer.project.state import update_agent_architecture_method_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    original_count = (
        agent.read_text(encoding="utf-8").count("- 架构方法:")
    )
    assert original_count == 1

    changed = update_agent_architecture_method_line(agent, "英雄之旅")

    assert changed is True
    text = agent.read_text(encoding="utf-8")
    assert text.count("- 架构方法:") == 1
    assert "- 架构方法: 英雄之旅" in text


def test_update_agent_architecture_method_line_preserves_genre_line(
    tmp_path: Path,
) -> None:
    """更新架构方法不应破坏 ``题材:`` 行（保留其它元数据）。"""

    from writer.project.state import update_agent_architecture_method_line

    workspace = create_workspace("novel", tmp_path, genre="玄幻")
    agent = workspace.root / "AGENT.md"
    # 先用 append_agent_requirements 模拟附加段
    from writer.project.state import append_agent_requirements

    append_agent_requirements(agent, "风格: 轻松")

    changed = update_agent_architecture_method_line(agent, "三明治架构")

    assert changed is True
    text = agent.read_text(encoding="utf-8")
    assert "- 题材: 玄幻" in text
    assert "- 架构方法: 三明治架构" in text
    assert "## 基本要求" in text
    assert "风格: 轻松" in text


def test_update_agent_architecture_method_line_empty_is_noop(
    tmp_path: Path,
) -> None:
    """空字符串 / 纯空白输入视作 no-op,不写也不删。"""

    from writer.project.state import update_agent_architecture_method_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    before = agent.read_text(encoding="utf-8")

    assert update_agent_architecture_method_line(agent, "") is False
    assert update_agent_architecture_method_line(agent, "   ") is False
    assert agent.read_text(encoding="utf-8") == before


def test_refresh_agent_file_preserves_architecture_method(tmp_path: Path) -> None:
    """状态切换时, ``refresh_agent_file`` 保留 ``架构方法:`` 行不被清空。"""

    from writer.project.state import refresh_agent_file

    workspace = create_workspace("novel", tmp_path)
    # 手工把方法改为「三幕结构」
    agent = workspace.root / "AGENT.md"
    from writer.project.state import update_agent_architecture_method_line

    update_agent_architecture_method_line(agent, "三幕结构")
    # 触发状态变化 (S1 → S2 by writing 大纲)
    (workspace.root / "大纲" / "大纲.md").write_text("x", encoding="utf-8")

    refresh_agent_file(workspace.root)

    text = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "- 架构方法: 三幕结构" in text
    assert "state: S2" in text


# ---------------------------------------------------------------------------
# 预计总字数 (per 2026-07-16 目录落地)
# ---------------------------------------------------------------------------


def test_render_agent_file_includes_total_words_when_set() -> None:
    """``render_agent_file(..., total_words=...)`` 写入对应 ``预计总字数:`` 行。"""

    from writer.project.state import render_agent_file

    text = render_agent_file(
        "测试项目",
        ProjectState.INITIALIZED,
        total_words=300000,
    )
    assert "- 预计总字数: 300000" in text
    # 其它两行未传 → 不渲染
    assert "预计总章数" not in text
    assert "- 分卷:" not in text


def test_render_agent_file_omits_total_words_when_none() -> None:
    """``render_agent_file`` 默认不写 ``预计总字数:`` 行。"""

    from writer.project.state import render_agent_file

    text = render_agent_file("测试项目", ProjectState.INITIALIZED)
    assert "预计总字数" not in text


def test_render_agent_file_includes_total_chapters_and_volumes_when_set() -> None:
    """三行新字段（字数 / 章数 / 分卷）一起传入时全部渲染。"""

    from writer.project.state import render_agent_file

    text = render_agent_file(
        "测试项目",
        ProjectState.HAS_TOC,
        total_words=300000,
        total_chapters=100,
        volumes_text="卷一(40章)/卷二(30章)/卷三(30章)",
    )
    assert "- 预计总字数: 300000" in text
    assert "- 预计总章数: 100" in text
    assert "- 分卷: 卷一(40章)/卷二(30章)/卷三(30章)" in text


def test_read_total_words_falls_back_to_none(tmp_path: Path) -> None:
    """AGENT.md 缺失或没有 ``预计总字数:`` 行时,返回 ``None``。"""

    from writer.project.state import read_total_words_from_agent

    assert read_total_words_from_agent(tmp_path / "missing.md") is None

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    assert read_total_words_from_agent(agent) is None


def test_read_total_words_parses_bare_and_list_forms(tmp_path: Path) -> None:
    """``预计总字数:`` 行兼容 bare / ``- `` / ``* `` 前缀。"""

    from writer.project.state import read_total_words_from_agent

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    original = agent.read_text(encoding="utf-8")

    text = original + "\n预计总字数: 300000\n"
    agent.write_text(text, encoding="utf-8")
    assert read_total_words_from_agent(agent) == 300000

    text = original + "\n- 预计总字数: 500000\n"
    agent.write_text(text, encoding="utf-8")
    assert read_total_words_from_agent(agent) == 500000

    text = original + "\n* 预计总字数: 1000000\n"
    agent.write_text(text, encoding="utf-8")
    assert read_total_words_from_agent(agent) == 1000000


def test_read_total_words_returns_none_for_zero_or_unparseable(tmp_path: Path) -> None:
    """``预计总字数: 0`` / ``预计总字数: abc`` / 空白值全部回退 ``None``。"""

    from writer.project.state import read_total_words_from_agent

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    original = agent.read_text(encoding="utf-8")

    # 0 → None（无 0 字小说）
    agent.write_text(original + "\n预计总字数: 0\n", encoding="utf-8")
    assert read_total_words_from_agent(agent) is None

    # 非数字 → None
    agent.write_text(original + "\n预计总字数: thirty万\n", encoding="utf-8")
    assert read_total_words_from_agent(agent) is None

    # 空白值 → None
    agent.write_text(original + "\n预计总字数:    \n", encoding="utf-8")
    assert read_total_words_from_agent(agent) is None


def test_update_agent_total_words_line_inserts_when_missing(tmp_path: Path) -> None:
    """AGENT.md 没有该行时,插入到第一个 ``## ...`` 二级标题之前。"""

    from writer.project.state import update_agent_total_words_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    agent.write_text(
        "# 旧项目\n\n## 目录约定\n\n- 大纲/\n",
        encoding="utf-8",
    )

    changed = update_agent_total_words_line(agent, 300000)

    assert changed is True
    text = agent.read_text(encoding="utf-8")
    assert "- 预计总字数: 300000" in text
    assert "# 旧项目" in text
    assert "## 目录约定" in text


def test_update_agent_total_words_line_replaces_existing(tmp_path: Path) -> None:
    """AGENT.md 已含该行时,就地替换而非新增第二条。"""

    from writer.project.state import update_agent_total_words_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    update_agent_total_words_line(agent, 300000)
    assert agent.read_text(encoding="utf-8").count("- 预计总字数:") == 1

    changed = update_agent_total_words_line(agent, 500000)

    assert changed is True
    text = agent.read_text(encoding="utf-8")
    assert text.count("- 预计总字数:") == 1
    assert "- 预计总字数: 500000" in text


def test_update_agent_total_words_line_preserves_other_fields(tmp_path: Path) -> None:
    """更新字数不应破坏 ``题材:`` / ``架构方法:`` / ``## 基本要求`` 等元数据。"""

    from writer.project.state import (
        append_agent_requirements,
        update_agent_total_words_line,
    )

    workspace = create_workspace("novel", tmp_path, genre="玄幻")
    agent = workspace.root / "AGENT.md"
    append_agent_requirements(agent, "风格: 轻松")

    changed = update_agent_total_words_line(agent, 800000)

    assert changed is True
    text = agent.read_text(encoding="utf-8")
    assert "- 题材: 玄幻" in text
    assert "- 架构方法: 雪花法" in text
    assert "- 预计总字数: 800000" in text
    assert "## 基本要求" in text
    assert "风格: 轻松" in text


def test_update_agent_total_words_line_zero_or_negative_is_noop(
    tmp_path: Path,
) -> None:
    """``0`` / 负数 / ``None`` 视作无效输入,no-op。"""

    from writer.project.state import update_agent_total_words_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    before = agent.read_text(encoding="utf-8")

    assert update_agent_total_words_line(agent, 0) is False
    assert update_agent_total_words_line(agent, -100) is False
    assert update_agent_total_words_line(agent, None) is False
    assert agent.read_text(encoding="utf-8") == before


def test_update_agent_total_words_line_missing_file_is_noop(tmp_path: Path) -> None:
    """AGENT.md 不存在时静默忽略,返回 ``False``,不抛异常。"""

    from writer.project.state import update_agent_total_words_line

    missing = tmp_path / "no_agent.md"
    assert missing.exists() is False
    assert update_agent_total_words_line(missing, 300000) is False


# ---------------------------------------------------------------------------
# 预计总章数 (per 2026-07-16 目录落地)
# ---------------------------------------------------------------------------


def test_render_agent_file_includes_total_chapters_when_set() -> None:
    """``render_agent_file(..., total_chapters=...)`` 写入对应行。"""

    from writer.project.state import render_agent_file

    text = render_agent_file(
        "测试项目",
        ProjectState.INITIALIZED,
        total_chapters=100,
    )
    assert "- 预计总章数: 100" in text


def test_read_total_chapters_falls_back_to_none(tmp_path: Path) -> None:
    """缺失或没有该行时,回退 ``None``。"""

    from writer.project.state import read_total_chapters_from_agent

    assert read_total_chapters_from_agent(tmp_path / "missing.md") is None

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    assert read_total_chapters_from_agent(agent) is None


def test_read_total_chapters_parses_list_prefix(tmp_path: Path) -> None:
    """兼容 bare / ``- `` 前缀。"""

    from writer.project.state import read_total_chapters_from_agent

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    original = agent.read_text(encoding="utf-8")

    agent.write_text(original + "\n- 预计总章数: 120\n", encoding="utf-8")
    assert read_total_chapters_from_agent(agent) == 120


def test_read_total_chapters_returns_none_for_zero_or_unparseable(
    tmp_path: Path,
) -> None:
    """``0`` / 非数字 / 空白 → ``None``。"""

    from writer.project.state import read_total_chapters_from_agent

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    original = agent.read_text(encoding="utf-8")

    agent.write_text(original + "\n预计总章数: 0\n", encoding="utf-8")
    assert read_total_chapters_from_agent(agent) is None

    agent.write_text(original + "\n预计总章数: many\n", encoding="utf-8")
    assert read_total_chapters_from_agent(agent) is None


def test_update_agent_total_chapters_line_inserts_and_replaces(tmp_path: Path) -> None:
    """插入与就地替换行为,等价 ``架构方法`` 行。"""

    from writer.project.state import update_agent_total_chapters_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    agent.write_text(
        "# 旧项目\n\n## 目录约定\n\n- 大纲/\n",
        encoding="utf-8",
    )

    assert update_agent_total_chapters_line(agent, 100) is True
    assert "- 预计总章数: 100" in agent.read_text(encoding="utf-8")

    assert update_agent_total_chapters_line(agent, 120) is True
    text = agent.read_text(encoding="utf-8")
    assert text.count("- 预计总章数:") == 1
    assert "- 预计总章数: 120" in text


def test_update_agent_total_chapters_line_zero_or_none_is_noop(tmp_path: Path) -> None:
    """``0`` / 负数 / ``None`` → no-op。"""

    from writer.project.state import update_agent_total_chapters_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    before = agent.read_text(encoding="utf-8")

    assert update_agent_total_chapters_line(agent, 0) is False
    assert update_agent_total_chapters_line(agent, None) is False
    assert agent.read_text(encoding="utf-8") == before


def test_update_agent_total_chapters_line_missing_file_is_noop(
    tmp_path: Path,
) -> None:
    """文件不存在静默返回 ``False``。"""

    from writer.project.state import update_agent_total_chapters_line

    missing = tmp_path / "no_agent.md"
    assert update_agent_total_chapters_line(missing, 50) is False


# ---------------------------------------------------------------------------
# 分卷 (per 2026-07-16 目录落地)
# ---------------------------------------------------------------------------


def test_render_agent_file_includes_volumes_text_when_set() -> None:
    """``render_agent_file(..., volumes_text=...)`` 渲染对应行。"""

    from writer.project.state import render_agent_file

    text = render_agent_file(
        "测试项目",
        ProjectState.HAS_TOC,
        volumes_text="卷一(40章)/卷二(30章)/卷三(30章)",
    )
    assert "- 分卷: 卷一(40章)/卷二(30章)/卷三(30章)" in text


def test_render_agent_file_omits_volumes_when_empty_or_none() -> None:
    """``None`` / 空字符串 / 纯空白 → 不写 ``分卷:`` 行。"""

    from writer.project.state import render_agent_file

    # ``分卷`` 字面会出现在 ``## 目录约定`` 段（"大纲、目录与分卷规划"），
    # 因此断言锚定 ``- 分卷:`` 字段行（非目录约定段）。
    assert "- 分卷:" not in render_agent_file("测试项目", ProjectState.HAS_TOC)
    assert "- 分卷:" not in render_agent_file(
        "测试项目",
        ProjectState.HAS_TOC,
        volumes_text="",
    )
    assert "- 分卷:" not in render_agent_file(
        "测试项目",
        ProjectState.HAS_TOC,
        volumes_text="   ",
    )


def test_read_volumes_falls_back_to_none(tmp_path: Path) -> None:
    """缺失或没有该行 → ``None``。"""

    from writer.project.state import read_volumes_from_agent

    assert read_volumes_from_agent(tmp_path / "missing.md") is None

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    assert read_volumes_from_agent(agent) is None


def test_read_volumes_parses_bare_and_list_forms(tmp_path: Path) -> None:
    """兼容 bare / list 前缀。"""

    from writer.project.state import read_volumes_from_agent

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    original = agent.read_text(encoding="utf-8")

    text = original.replace(
        "- 架构方法: 雪花法",
        "- 架构方法: 雪花法\n分卷: 卷一(20章)/卷二(40章)",
    )
    agent.write_text(text, encoding="utf-8")
    assert read_volumes_from_agent(agent) == "卷一(20章)/卷二(40章)"

    text = original.replace(
        "- 架构方法: 雪花法",
        "- 架构方法: 雪花法\n- 分卷: 卷一(10章)/卷二(10章)",
    )
    agent.write_text(text, encoding="utf-8")
    assert read_volumes_from_agent(agent) == "卷一(10章)/卷二(10章)"


def test_update_agent_volumes_line_inserts_and_replaces(tmp_path: Path) -> None:
    """插入与就地替换等价于 ``架构方法`` 行。"""

    from writer.project.state import update_agent_volumes_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    agent.write_text(
        "# 旧项目\n\n## 目录约定\n\n- 大纲/\n",
        encoding="utf-8",
    )

    assert update_agent_volumes_line(agent, "卷一(20章)/卷二(40章)") is True
    assert "- 分卷: 卷一(20章)/卷二(40章)" in agent.read_text(encoding="utf-8")

    assert update_agent_volumes_line(agent, "卷一(30章)/卷二(30章)/卷三(40章)") is True
    text = agent.read_text(encoding="utf-8")
    assert text.count("- 分卷:") == 1
    assert "- 分卷: 卷一(30章)/卷二(30章)/卷三(40章)" in text


def test_update_agent_volumes_line_empty_or_whitespace_is_noop(
    tmp_path: Path,
) -> None:
    """空字符串 / 纯空白 → no-op。"""

    from writer.project.state import update_agent_volumes_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    before = agent.read_text(encoding="utf-8")

    assert update_agent_volumes_line(agent, "") is False
    assert update_agent_volumes_line(agent, "   ") is False
    assert agent.read_text(encoding="utf-8") == before


def test_update_agent_volumes_line_preserves_other_fields(tmp_path: Path) -> None:
    """更新分卷不应破坏字数 / 章数 / 题材等元数据。"""

    from writer.project.state import (
        update_agent_total_chapters_line,
        update_agent_total_words_line,
        update_agent_volumes_line,
    )

    workspace = create_workspace("novel", tmp_path, genre="玄幻")
    agent = workspace.root / "AGENT.md"
    update_agent_total_words_line(agent, 300000)
    update_agent_total_chapters_line(agent, 100)

    changed = update_agent_volumes_line(agent, "卷一(40章)/卷二(60章)")

    assert changed is True
    text = agent.read_text(encoding="utf-8")
    assert "- 题材: 玄幻" in text
    assert "- 预计总字数: 300000" in text
    assert "- 预计总章数: 100" in text
    assert "- 分卷: 卷一(40章)/卷二(60章)" in text


def test_update_agent_volumes_line_missing_file_is_noop(tmp_path: Path) -> None:
    """文件不存在静默返回 ``False``。"""

    from writer.project.state import update_agent_volumes_line

    missing = tmp_path / "no_agent.md"
    assert update_agent_volumes_line(missing, "卷一(20章)") is False


# ---------------------------------------------------------------------------
# refresh_agent_file 保留三行新字段 (per 2026-07-16 目录落地)
# ---------------------------------------------------------------------------


def test_refresh_agent_file_preserves_total_words_and_chapters(tmp_path: Path) -> None:
    """状态切换时, ``refresh_agent_file`` 保留字数 / 章数 / 分卷行不被清空。"""

    from writer.project.state import (
        update_agent_total_chapters_line,
        update_agent_total_words_line,
    )

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    update_agent_total_words_line(agent, 300000)
    update_agent_total_chapters_line(agent, 100)

    # 触发状态变化 (S1 → S2)
    (workspace.root / "大纲" / "大纲.md").write_text("x", encoding="utf-8")
    refresh_agent_file(workspace.root)

    text = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "- 预计总字数: 300000" in text
    assert "- 预计总章数: 100" in text
    assert "state: S2" in text


def test_refresh_agent_file_preserves_volumes(tmp_path: Path) -> None:
    """状态切换时, ``refresh_agent_file`` 保留 ``分卷:`` 行不被清空。"""

    from writer.project.state import update_agent_volumes_line

    workspace = create_workspace("novel", tmp_path)
    agent = workspace.root / "AGENT.md"
    update_agent_volumes_line(agent, "卷一(40章)/卷二(60章)")

    (workspace.root / "大纲" / "大纲.md").write_text("x", encoding="utf-8")
    refresh_agent_file(workspace.root)

    text = (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert "- 分卷: 卷一(40章)/卷二(60章)" in text
