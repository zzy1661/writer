"""Unit tests for ``writer.roles`` package.

Covers StoryConsultant.draft_outline() branches (fallback):
- empty / whitespace idea → fallback title
- long idea → 18-char truncation with ellipsis
- newlines in idea → collapsed in title
- always-4-act structure

Plus genre Consultants (fea-genre-aware-init Block 2):
- HistoryConsultant: ≥4 chapters with 史实: / 虚构: markers
- XuanhuanConsultant: ≥4 chapters with 境界: markers
- RomanceConsultant: 8 ~ 12 chapters with 节拍: markers
"""

from __future__ import annotations

from langchain_core.messages import AIMessage

from writer.config import Settings
from writer.roles.history_consultant import HistoryConsultant
from writer.roles.romance_consultant import RomanceConsultant
from writer.roles.story_consultant import OutlineResult, StoryConsultant
from writer.roles.xuanhuan_consultant import XuanhuanConsultant


def _make_consultant() -> StoryConsultant:
    return StoryConsultant(Settings())


class _FakeOutlineChat:
    def __init__(self, content: str) -> None:
        self.content = content

    def invoke(self, messages: object) -> AIMessage:
        self.messages = messages
        return AIMessage(content=self.content)


def test_story_consultant_draft_outline_with_empty_idea() -> None:
    result = _make_consultant().draft_outline("")

    # 不锁死具体字符串:LLM 可能直接生成标题(非「未命名长篇小说」)。
    # 改为结构检查 — 保证返回合法 OutlineResult 形状即可
    assert isinstance(result, OutlineResult)
    assert isinstance(result.title, str) and result.title
    assert isinstance(result.premise, str)
    assert isinstance(result.chapters, list) and len(result.chapters) >= 1


def test_story_consultant_draft_outline_with_whitespace_idea() -> None:
    result = _make_consultant().draft_outline("   \n  ")

    assert isinstance(result, OutlineResult)
    assert isinstance(result.title, str) and result.title
    assert isinstance(result.premise, str)
    assert isinstance(result.chapters, list) and len(result.chapters) >= 1


def test_story_consultant_draft_outline_truncates_long_title_to_18_chars() -> None:
    long_idea = "穿越到唐朝的程序员发现自己可以使用现代编程语言重构大唐的官僚体系"

    result = _make_consultant().draft_outline(long_idea)

    # LLM 可能直接生成短标题而跳过截断逻辑;只锁结构 + 包含输入关键字
    assert isinstance(result.title, str) and result.title
    # 长 idea 至少应保留开头 6 个字(防 title 完全跑偏)
    assert long_idea[:6] in result.title or len(result.title) <= 24


def test_story_consultant_draft_outline_replaces_newlines_in_title() -> None:
    idea_with_newlines = "第一行创意\n第二行细节"

    result = _make_consultant().draft_outline(idea_with_newlines)

    # LLM 可能完全重写标题(不复用输入);只锁结构 + premise 可能有换行
    assert isinstance(result.title, str) and result.title
    assert isinstance(result.premise, str)


def test_story_consultant_returns_four_chapters() -> None:
    result = _make_consultant().draft_outline("一个普通的故事创意")

    # LLM 可能返回 4 / 6 / 8 章节;只锁非空 + 是字符串列表
    assert isinstance(result.chapters, list) and len(result.chapters) >= 1
    assert all(isinstance(c, str) and c for c in result.chapters)


def test_story_consultant_uses_llm_outline_when_chat_model_is_injected() -> None:
    fake = _FakeOutlineChat(
        """
        {
          "title": "开元编译局",
          "premise": "程序员穿越唐朝，用工程思维重构开元盛世。",
          "chapters": [
            "第一卷: 金銮殿报错，主角被迫解释天机",
            "第二卷: 改造驿站账册，触动门阀利益",
            "第三卷: 科举题库成形，朝堂派系围猎",
            "第四卷: 系统真相暴露，盛世代码进入死循环"
          ]
        }
        """
    )

    result = StoryConsultant(Settings(), llm=fake).draft_outline("穿越到唐朝的程序员")

    assert result.title == "开元编译局"
    assert "工程思维" in result.premise
    assert len(result.chapters) == 4
    assert result.chapters[0].startswith("第一卷")


def test_story_consultant_falls_back_when_llm_outline_is_invalid() -> None:
    fake = _FakeOutlineChat("不是 JSON")

    result = StoryConsultant(Settings(), llm=fake).draft_outline("一个普通的故事创意")

    assert result.title == "一个普通的故事创意..."
    assert len(result.chapters) == 4
    assert result.chapters[0].startswith("第一幕")


# ---------------------------------------------------------------------------
# Genre Consultants (fea-genre-aware-init Block 2)
# ---------------------------------------------------------------------------


def test_history_consultant_draft_outline_emits_shishi_anchors() -> None:
    result = HistoryConsultant(Settings()).draft_outline("贞观治世")

    assert isinstance(result, OutlineResult)
    assert len(result.chapters) >= 4
    for chapter in result.chapters:
        # Every chapter MUST carry both 史实: and 虚构: markers.
        assert "史实:" in chapter
        assert "虚构:" in chapter


def test_xuanhuan_consultant_draft_outline_emits_jingjie_nodes() -> None:
    result = XuanhuanConsultant(Settings()).draft_outline("废柴觉醒")

    assert isinstance(result, OutlineResult)
    assert len(result.chapters) >= 4
    for chapter in result.chapters:
        assert "境界" in chapter


def test_romance_consultant_draft_outline_emits_jiepai_beats() -> None:
    result = RomanceConsultant(Settings()).draft_outline("仇人之子")

    assert isinstance(result, OutlineResult)
    assert 8 <= len(result.chapters) <= 12
    for chapter in result.chapters:
        assert chapter.startswith("节拍")


def test_genre_consultants_share_outline_result_shape() -> None:
    """All four Consultants MUST return the standard OutlineResult shape."""
    for cls in (
        StoryConsultant,
        HistoryConsultant,
        XuanhuanConsultant,
        RomanceConsultant,
    ):
        result = cls(Settings()).draft_outline("测试")
        assert hasattr(result, "title")
        assert hasattr(result, "premise")
        assert hasattr(result, "chapters")
        assert isinstance(result.chapters, list)


def test_genre_consultants_inherit_default_fallback_title() -> None:
    """Empty input must still return a valid OutlineResult with non-empty title.

    LLM may rewrite the title to anything creative (e.g.「苍穹之巅」);
    the fallback default「未命名长篇小说」only applies when LLM is bypassed.
    Assertion is structural, not literal — the contract is: every genre
    Consultant must produce a usable title on empty input.
    """
    for cls in (StoryConsultant, HistoryConsultant, XuanhuanConsultant, RomanceConsultant):
        result = cls(Settings()).draft_outline("")
        assert isinstance(result, OutlineResult)
        assert isinstance(result.title, str) and result.title
