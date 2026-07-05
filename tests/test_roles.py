"""Unit tests for ``writer.roles.story_consultant``.

Covers StoryConsultant.draft_outline() branches:
- empty / whitespace idea → fallback title
- long idea → 18-char truncation with ellipsis
- newlines in idea → collapsed in title
- always-4-act structure
"""

from __future__ import annotations

from writer.config import Settings
from writer.roles.story_consultant import OutlineResult, StoryConsultant


def _make_consultant() -> StoryConsultant:
    return StoryConsultant(Settings())


def test_story_consultant_draft_outline_with_empty_idea() -> None:
    result = _make_consultant().draft_outline("")

    assert isinstance(result, OutlineResult)
    assert result.title == "未命名长篇小说"
    assert result.premise == ""
    assert len(result.chapters) == 4


def test_story_consultant_draft_outline_with_whitespace_idea() -> None:
    result = _make_consultant().draft_outline("   \n  ")

    assert result.title == "未命名长篇小说"
    assert result.premise == ""  # whitespace-only stripped to empty
    assert len(result.chapters) == 4


def test_story_consultant_draft_outline_truncates_long_title_to_18_chars() -> None:
    long_idea = "穿越到唐朝的程序员发现自己可以使用现代编程语言重构大唐的官僚体系"

    result = _make_consultant().draft_outline(long_idea)

    # 18 chars of content + 3-char ellipsis "..."
    assert len(result.title) == 21
    assert result.title.endswith("...")
    assert result.title.startswith(long_idea[:18])


def test_story_consultant_draft_outline_replaces_newlines_in_title() -> None:
    idea_with_newlines = "第一行创意\n第二行细节"

    result = _make_consultant().draft_outline(idea_with_newlines)

    assert "\n" not in result.title
    assert "第一行创意" in result.title
    assert "第二行细节" in result.title
    # The title should keep a single space between formerly-newline-separated parts
    assert "第一行创意 第二行细节..." in result.title
    # The premise keeps the original newlines — only the title collapses them
    assert "\n" in result.premise


def test_story_consultant_returns_four_chapters() -> None:
    result = _make_consultant().draft_outline("一个普通的故事创意")

    assert len(result.chapters) == 4
    assert result.chapters[0].startswith("第一幕")
    assert result.chapters[1].startswith("第二幕")
    assert result.chapters[2].startswith("第三幕")
    assert result.chapters[3].startswith("第四幕")
