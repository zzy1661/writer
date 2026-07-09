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


def test_extract_init_brief_text_supports_flag_form() -> None:
    from writer.project.init_brief import extract_init_brief_text

    assert extract_init_brief_text("/init --brief 程序员穿越唐朝") == "程序员穿越唐朝"
    assert extract_init_brief_text("/init -b 程序员穿越唐朝") == "程序员穿越唐朝"
