"""Unit tests for :mod:`writer.prompts.agents`."""

from __future__ import annotations

from langchain_core.prompts import ChatPromptTemplate

from writer.prompts.agents import (
    FALLBACK_OUTLINE_CHAPTERS,
    INIT_BRIEF_TEMPLATE,
    OUTLINE_TEMPLATE_HISTORY,
    OUTLINE_TEMPLATE_ROMANCE,
    OUTLINE_TEMPLATE_STORY,
    OUTLINE_TEMPLATE_XUANHUAN,
    TOC_TEMPLATE,
)

# ---------------------------------------------------------------------------
# Outline templates — one per genre
# ---------------------------------------------------------------------------


def _render_outline(template: ChatPromptTemplate) -> str:
    messages = template.format_messages(user_message="创意: 测试")
    return messages[0].content if isinstance(messages[0].content, str) else str(messages[0].content)


def test_outline_story_uses_neutral_identity() -> None:
    """The default outline template uses the genre-neutral identity."""

    system = _render_outline(OUTLINE_TEMPLATE_STORY)
    assert "编剧顾问" in system
    # Should not claim a genre specialism
    assert "历史题材" not in system
    assert "言情题材" not in system
    assert "玄幻题材" not in system


def test_outline_history_uses_history_identity() -> None:
    """The history outline template advertises the 历史 specialism."""

    system = _render_outline(OUTLINE_TEMPLATE_HISTORY)
    assert "历史题材" in system
    assert "史实" in system
    assert "虚构" in system


def test_outline_romance_uses_romance_identity() -> None:
    """The romance outline template advertises the 言情 specialism."""

    system = _render_outline(OUTLINE_TEMPLATE_ROMANCE)
    assert "言情题材" in system
    assert "GMC" in system
    assert "节拍" in system


def test_outline_xuanhuan_uses_xuanhuan_identity() -> None:
    """The xuanhuan outline template advertises the 玄幻 specialism."""

    system = _render_outline(OUTLINE_TEMPLATE_XUANHUAN)
    assert "玄幻题材" in system
    assert "境界" in system


def test_outline_genres_have_distinct_identities() -> None:
    """The four outline templates must not be textually identical."""

    texts = {
        "story": _render_outline(OUTLINE_TEMPLATE_STORY),
        "history": _render_outline(OUTLINE_TEMPLATE_HISTORY),
        "romance": _render_outline(OUTLINE_TEMPLATE_ROMANCE),
        "xuanhuan": _render_outline(OUTLINE_TEMPLATE_XUANHUAN),
    }
    assert len(set(texts.values())) == 4  # pairwise distinct


# ---------------------------------------------------------------------------
# TOC template — single shared template
# ---------------------------------------------------------------------------


def test_toc_template_uses_neutral_identity() -> None:
    """TOC is not genre-split in this iteration (per prompts plan)."""

    messages = TOC_TEMPLATE.format_messages(outline_text="# 书\n- 第一幕")
    system = messages[0].content if isinstance(messages[0].content, str) else str(messages[0].content)

    assert "编剧顾问" in system
    # Human message carries the outline
    human = messages[1]
    human_text = human.content if isinstance(human.content, str) else str(human.content)
    assert "大纲" in human_text
    assert "# 书" in human_text


# ---------------------------------------------------------------------------
# Init brief template — single shared template
# ---------------------------------------------------------------------------


def test_init_brief_template_uses_neutral_identity() -> None:
    """Init-brief is not genre-split in this iteration (per prompts plan)."""

    messages = INIT_BRIEF_TEMPLATE.format_messages(brief="一个穿越者")
    system = messages[0].content if isinstance(messages[0].content, str) else str(messages[0].content)

    assert "编剧顾问" in system
    human = messages[1]
    human_text = human.content if isinstance(human.content, str) else str(human.content)
    assert "一个穿越者" in human_text


# ---------------------------------------------------------------------------
# Deterministic fallback chapter lists
# ---------------------------------------------------------------------------


def test_fallback_outline_chapters_covers_all_genres() -> None:
    """Every genre key in ``GENRE`` ClassVars must have a fallback."""

    # The keys here mirror the four ClassVar values on the Agents.
    expected_keys = {"other", "历史", "言情", "玄幻"}
    assert expected_keys.issubset(FALLBACK_OUTLINE_CHAPTERS.keys())


def test_fallback_history_chapters_have_shishi_and_xugou_markers() -> None:
    """Per the fea-genre-aware-init proposal, history fallback uses 史实:/虚构:."""

    for chapter in FALLBACK_OUTLINE_CHAPTERS["历史"]:
        assert "史实:" in chapter
        assert "虚构:" in chapter


def test_fallback_xuanhuan_chapters_have_jingjie_markers() -> None:
    """Per the fea-genre-aware-init proposal, xuanhuan fallback uses 境界<N>."""

    for chapter in FALLBACK_OUTLINE_CHAPTERS["玄幻"]:
        assert "境界" in chapter


def test_fallback_romance_chapters_have_jiepai_markers() -> None:
    """Per the fea-genre-aware-init proposal, romance fallback uses 节拍<N>."""

    for chapter in FALLBACK_OUTLINE_CHAPTERS["言情"]:
        assert chapter.startswith("节拍")


def test_fallback_other_chapters_have_four_act_structure() -> None:
    """The default fallback is the four-act structure from the parent."""

    chapters = FALLBACK_OUTLINE_CHAPTERS["other"]
    assert len(chapters) == 4
    assert chapters[0].startswith("第一幕")
    assert chapters[1].startswith("第二幕")
    assert chapters[2].startswith("第三幕")
    assert chapters[3].startswith("第四幕")
