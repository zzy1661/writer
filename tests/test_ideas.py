"""Tests for ``writer.project.ideas``."""

from __future__ import annotations

from pathlib import Path

from langchain_core.messages import AIMessage, HumanMessage

from writer.config import Settings
from writer.project.ideas import IdeasContext, build_outline_user_message, load_ideas_context
from writer.project.workspace import create_workspace
from writer.roles.story_agent import StoryAgent


def test_load_ideas_context_reads_core_and_supplementary(tmp_path: Path) -> None:
    workspace = create_workspace("ideas-load", tmp_path, with_ideas_dir=True)
    ideas_dir = workspace.root / "创意"
    (ideas_dir / "核心创意.md").write_text("# 核心\n\n林远穿越到杀戮世界。", encoding="utf-8")
    (ideas_dir / "角色灵感.md").write_text("主角：游戏设计师林远。", encoding="utf-8")
    (ideas_dir / "README.md").write_text("占位", encoding="utf-8")

    ctx = load_ideas_context(workspace.root)

    assert ctx.core_idea is not None
    assert "林远穿越" in ctx.core_idea
    assert len(ctx.supplementary_docs) == 1
    assert ctx.supplementary_docs[0][0] == "角色灵感.md"
    assert "游戏设计师" in ctx.supplementary_docs[0][1]


def test_build_outline_user_message_prioritizes_core_idea() -> None:
    ctx = IdeasContext(
        core_idea="# 核心创意\n\n温馨城市变成杀戮世界。",
        supplementary_docs=(("设定.md", "双世界对照。"),),
    )
    message = build_outline_user_message(
        user_instruction="强调反差",
        ideas=ctx,
    )

    assert "核心创意（大纲须以此为中心展开）" in message
    assert "温馨城市变成杀戮世界" in message
    assert "### 设定.md" in message
    assert "双世界对照" in message
    assert "本次补充指令" in message
    assert "强调反差" in message
    assert "不得偏离核心创意" in message


def test_draft_outline_llm_prompt_includes_ideas_context(tmp_path: Path) -> None:
    workspace = create_workspace("ideas-outline", tmp_path, with_ideas_dir=True)
    ideas_dir = workspace.root / "创意"
    (ideas_dir / "核心创意.md").write_text(
        "# 核心创意\n\n林远穿越到他写的温馨游戏，却落入杀戮世界。",
        encoding="utf-8",
    )
    (ideas_dir / "世界观.md").write_text("两个世界规则相反。", encoding="utf-8")

    class _CapturingChat:
        def invoke(self, messages: object) -> AIMessage:
            self.messages = messages
            return AIMessage(
                content=(
                    '{"title": "杀戮都市", "premise": "双世界反差", '
                    '"chapters": ["第一幕", "第二幕", "第三幕", "第四幕"]}'
                )
            )

    fake = _CapturingChat()
    StoryAgent(Settings(), llm=fake).draft_outline(
        "突出主角认知错位",
        project_root=workspace.root,
    )

    human = next(m for m in fake.messages if isinstance(m, HumanMessage))
    assert "林远穿越到他写的温馨游戏" in human.content
    assert "世界观.md" in human.content
    assert "突出主角认知错位" in human.content
