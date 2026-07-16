"""Tests for post-init creative brief processing."""

from __future__ import annotations

from langchain_core.messages import AIMessage

from writer.config import Settings
from writer.project.init_brief import apply_init_brief

# ---------------------------------------------------------------------------
# process_init_brief direct (covers the function-based capability introduced
# by ``chg-remove-roles``: ``writer.roles.StoryAgent`` is gone, replaced by
# :func:`writer.agents.process_init_brief`).
# ---------------------------------------------------------------------------


class _FakeBriefChat:
    def __init__(self, content: str) -> None:
        self.content = content

    def invoke(self, messages: object) -> AIMessage:
        return AIMessage(content=self.content)


def test_apply_init_brief_writes_core_idea_and_agent_requirements(tmp_path) -> None:  # noqa: ANN001
    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n\n", encoding="utf-8")

    fake = _FakeBriefChat(
        """
        {
          "core_idea": "# 核心创意\\n\\n程序员穿越唐朝，用代码改造官僚体系。",
          "requirements": "- 篇幅: 30 万字\\n- 风格: 轻松历史架空"
        }
        """
    )
    result = apply_init_brief(
        project,
        "程序员穿越唐朝",
        settings=Settings(),
        llm=fake,
    )

    assert result.source == "llm"
    core = (project / "创意" / "核心创意.md").read_text(encoding="utf-8")
    agent = (project / "AGENT.md").read_text(encoding="utf-8")
    assert "核心创意" in core
    assert "官僚体系" in core
    assert "## 基本要求" in agent
    assert "30 万字" in agent


def test_process_init_brief_fallback_without_api_key() -> None:
    """``process_init_brief`` falls back to the deterministic Markdown body.

    Updated 2026-07-09 (``chg-remove-roles``): the previous test
    round-tripped through ``apply_init_brief`` so the ``StoryAgent``
    fallback path got exercised. We now invoke
    :func:`writer.agents.process_init_brief` directly and assert the
    structured ``source='fallback'`` contract.
    """

    from writer.agents import process_init_brief

    result = process_init_brief(
        "一个废土少年的故事", settings=Settings(api_key=None)
    )

    assert result.source == "fallback"
    assert "核心创意" in result.core_idea
    assert "一个废土少年的故事" in result.core_idea


def test_process_init_brief_fallback_writes_files_via_apply(tmp_path) -> None:  # noqa: ANN001
    """End-to-end: ``apply_init_brief`` with no API key writes the files."""

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n\n", encoding="utf-8")

    apply_init_brief(
        project,
        "一个废土少年的故事",
        settings=Settings(api_key=None),
    )

    assert (project / "创意" / "核心创意.md").is_file()


# ---------------------------------------------------------------------------
# Helpers around `/init <brief>` parsing (unchanged across the rewrite).
# ---------------------------------------------------------------------------


def test_should_run_init_brief_on_bound_s1_project(tmp_path) -> None:  # noqa: ANN001
    from writer.project import create_workspace
    from writer.project.init_brief import should_run_init_brief

    workspace = create_workspace("novel", tmp_path)
    brief = (
        "林远穿越到了他写的游戏中。但他写的游戏是一个充满温馨故事的城市，"
        "然而他穿越到的这个世界是一个充满杀戮和罪恶的世界。"
    )

    assert should_run_init_brief(
        f"/init {brief}",
        project_root=workspace.root,
        project_state="S1",
    )


def test_should_not_run_init_brief_for_project_name_at_s0() -> None:
    from writer.project.init_brief import should_run_init_brief

    assert not should_run_init_brief(
        "/init 我的小说",
        project_root=None,
        project_state="S0",
    )


def test_extract_init_brief_text_strips_init_prefix() -> None:
    """``extract_init_brief_text`` 现在只剥离 ``/init`` 前缀,把
    剩余文本当作故事核心创意。``--brief`` / ``-b`` flag 形式已于
    2026-07-14 删除(改用纯 ``/init <故事梗概>`` 形式)。
    """
    from writer.project.init_brief import extract_init_brief_text

    assert extract_init_brief_text("/init 程序员穿越唐朝") == "程序员穿越唐朝"
    assert extract_init_brief_text("/init") == ""
    assert extract_init_brief_text("/init   ") == ""


# ---------------------------------------------------------------------------
# ``apply_genre_and_brief`` — REPL ``/init <brief>`` 后端
# ---------------------------------------------------------------------------


def test_apply_genre_and_brief_creates_scaffold_and_writes_brief(
    tmp_path,
) -> None:  # noqa: ANN001
    """多题材下脚手架补建 + brief 写入一次性完成。"""

    from writer.cli._init_backend import apply_genre_and_brief

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text(
        "# novel\n\n## 当前状态\n\n- state: S1\n- label: 初始化\n",
        encoding="utf-8",
    )
    # 伏笔/伏笔表.md 是所有题材共有基础脚手架（per 2026-07-17）——
    # 正常由 ``create_workspace`` 创建；本测试手工建项目,显式补文件以
    # 模拟生产路径,再验证 ``apply_genre_and_brief`` 对其是 no-op（additive）。
    (project / "伏笔").mkdir()
    (project / "伏笔" / "伏笔表.md").write_text(
        "# 伏笔表\n\n| ID | 描述 | 埋伏章节 | 回收章节 | 标签 | 状态 |\n|----|------|---------|---------|------|------|\n",
        encoding="utf-8",
    )

    outcome = apply_genre_and_brief(
        project,
        genres=["历史", "玄幻"],
        brief="林远穿越到他写的游戏中，世界观与预设相反。",
        settings=Settings(api_key=None),
    )

    relative = sorted(
        p.relative_to(project).as_posix() for p in outcome.created_files
    )
    assert "史实/年表.md" in relative
    assert "史实/人物.md" in relative
    # 伏笔/伏笔表.md 已在 base scaffold 创建,apply_genre 不再添加。
    assert "伏笔/伏笔表.md" not in relative
    assert (project / "大纲" / "境界表.md").is_file()
    assert (project / "伏笔" / "伏笔表.md").is_file()
    assert (project / "创意" / "核心创意.md").is_file()
    assert outcome.brief_source == "fallback"
    assert "历史" in outcome.selected_genres
    assert "玄幻" in outcome.selected_genres


def test_apply_genre_and_brief_updates_genre_line_when_changed(
    tmp_path,
) -> None:  # noqa: ANN001
    """当题材与磁盘不同步时 ``genre_line_changed=True``。"""

    from writer.cli._init_backend import apply_genre_and_brief

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text(
        "# novel\n\n- 题材: 历史\n\n## 当前状态\n",
        encoding="utf-8",
    )

    outcome = apply_genre_and_brief(
        project,
        genres=["玄幻"],
        brief="一个废土少年的故事",
        settings=Settings(api_key=None),
    )

    assert outcome.genre_line_changed is True
    text = (project / "AGENT.md").read_text(encoding="utf-8")
    assert "- 题材: 玄幻" in text
    assert "题材: 历史" not in text


def test_apply_genre_and_brief_no_op_when_genre_unchanged(
    tmp_path,
) -> None:  # noqa: ANN001
    """已同步的题材不应触发 ``genre_line_changed``；所有脚手架已就位。"""

    from writer.cli._init_backend import apply_genre_and_brief
    from writer.project import apply_genre_scaffolding

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text(
        "# novel\n\n- 题材: 历史\n\n## 当前状态\n",
        encoding="utf-8",
    )
    # 预先 scaffold，让 ``apply_genre_scaffolding`` 命中既有文件
    apply_genre_scaffolding(project, ["历史"])

    outcome = apply_genre_and_brief(
        project,
        genres=["历史"],
        brief="林远穿越到他写的游戏中",
        settings=Settings(api_key=None),
    )

    assert outcome.genre_line_changed is False
    assert outcome.created_files == []  # 所有 scaffold 文件已存在


def test_apply_explore_outcome_creates_scaffold_and_arch_doc(tmp_path) -> None:  # noqa: ANN001
    from writer.cli._init_backend import apply_explore_outcome
    from writer.explore import ExploreOutcome

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text(
        "# novel\n\n## 当前状态\n\n- state: S1\n",
        encoding="utf-8",
    )

    result = apply_explore_outcome(
        project,
        ExploreOutcome(
            core_idea="# 核心\n\n程序员穿越到唐朝。",
            requirements="- 篇幅: 30 万字",
            genres=["历史"],
            architecture="三幕结构",
        ),
        settings=Settings(api_key=None),
    )

    assert result.selected_genres == ["历史"]
    assert (project / "史实" / "年表.md").is_file()
    assert (project / "创意" / "核心创意.md").read_text(encoding="utf-8").startswith(
        "# 核心"
    )
    agent = (project / "AGENT.md").read_text(encoding="utf-8")
    assert "- 题材: 历史" in agent
    assert "写作架构: 三幕结构" in agent
    assert "三幕结构" in (
        project / "大纲" / "写作架构.md"
    ).read_text(encoding="utf-8")


def test_apply_explore_outcome_skips_unknown_architecture(tmp_path, caplog) -> None:  # noqa: ANN001
    from writer.cli._init_backend import apply_explore_outcome
    from writer.explore import ExploreOutcome

    project = tmp_path / "novel"
    project.mkdir()
    (project / "AGENT.md").write_text("# novel\n", encoding="utf-8")

    apply_explore_outcome(
        project,
        ExploreOutcome("# 核心", "- 风格: 网文", ["其他"], "未知架构"),
        settings=Settings(api_key=None),
    )

    assert (project / "创意" / "核心创意.md").is_file()
    assert not (project / "大纲" / "写作架构.md").exists()
    assert "未知写作架构" in caplog.text
