"""Tests for ``writer.project.ideas``."""

from __future__ import annotations

from pathlib import Path

from writer.project.ideas import IdeasContext, build_outline_user_message, load_ideas_context
from writer.project.workspace import create_workspace


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


# ``test_draft_outline_llm_prompt_includes_ideas_context`` deleted in
# ``chg-remove-roles`` (2026-07-09): the underlying ``draft_outline``
# Python method is gone — outline generation is now driven by the LLM
# consuming ``writer/skills/_shipped/大纲/SKILL.md`` (which reads
# ``build_outline_user_message`` directly via ``safe_read_file``).
# ``build_outline_user_message`` is still tested above; the integration
# point moved from ``StoryAgent._draft_outline_with_llm`` into a
# Markdown directive.
