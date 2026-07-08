"""Unit tests verifying that the genre Consultants route through the prompt registry.

The point of centralising prompts is that each concrete Consultant
(``StoryConsultant`` / ``HistoryConsultant`` / ``RomanceConsultant`` /
``XuanhuanConsultant``) feeds the LLM the identity fragment that matches
its declared ``GENRE``. These tests pin that behaviour by injecting a
fake chat model that captures the messages it receives.
"""

from __future__ import annotations

from langchain_core.messages import AIMessage, SystemMessage

from writer.config import Settings
from writer.project.ideas import IdeasContext
from writer.roles.history_consultant import HistoryConsultant
from writer.roles.romance_consultant import RomanceConsultant
from writer.roles.story_consultant import StoryConsultant
from writer.roles.xuanhuan_consultant import XuanhuanConsultant


class _CapturingChat:
    """Fake chat model that records every message it receives."""

    def __init__(self, payload: str) -> None:
        self._payload = payload
        self.messages: list[object] = []

    def invoke(self, messages: object) -> AIMessage:
        self.messages = list(messages)  # type: ignore[arg-type]
        return AIMessage(content=self._payload)


def _system_texts(messages: list[object]) -> list[str]:
    out: list[str] = []
    for msg in messages:
        if isinstance(msg, SystemMessage):
            out.append(msg.content if isinstance(msg.content, str) else str(msg.content))
    return out


# A minimal but valid outline payload — keeps the LLM path happy.
_OUTLINE_PAYLOAD = (
    '{"title": "测试", "premise": "测试前提", '
    '"chapters": ["第一幕", "第二幕", "第三幕", "第四幕"]}'
)


def test_story_consultant_sends_neutral_identity() -> None:
    fake = _CapturingChat(_OUTLINE_PAYLOAD)
    StoryConsultant(Settings(), llm=fake).draft_outline("测试")

    systems = _system_texts(fake.messages)
    # The JSON-contract message + the central prompt's system message both
    # appear. We assert that at least one contains the neutral identity.
    assert any("编剧顾问" in text for text in systems)
    # And that none claim a genre specialism
    assert not any("历史题材" in text for text in systems)
    assert not any("言情题材" in text for text in systems)
    assert not any("玄幻题材" in text for text in systems)


def test_history_consultant_sends_history_identity() -> None:
    fake_llm = _CapturingChat(_OUTLINE_PAYLOAD)
    consultant = HistoryConsultant(Settings())
    # Inject the LLM directly so the no-API-key branch is bypassed.
    consultant._llm = fake_llm  # noqa: SLF001 — direct injection for test
    consultant._draft_outline_with_llm(  # noqa: SLF001
        idea="贞观之治",
        ideas=IdeasContext(),
    )

    systems = _system_texts(fake_llm.messages)
    assert any("历史题材" in text for text in systems)


def test_history_consultant_uses_genre_fallback_when_no_llm() -> None:
    """Without an API key, the history fallback must surface 史实:/虚构: markers."""

    result = HistoryConsultant(Settings()).draft_outline("贞观")
    assert all("史实:" in ch and "虚构:" in ch for ch in result.chapters)


def test_xuanhuan_consultant_sends_xuanhuan_identity() -> None:
    fake_llm = _CapturingChat(_OUTLINE_PAYLOAD)
    consultant = XuanhuanConsultant(Settings())
    consultant._llm = fake_llm  # noqa: SLF001
    consultant._draft_outline_with_llm(  # noqa: SLF001
        idea="废柴觉醒",
        ideas=IdeasContext(),
    )

    systems = _system_texts(fake_llm.messages)
    assert any("玄幻题材" in text for text in systems)


def test_xuanhuan_consultant_uses_genre_fallback_when_no_llm() -> None:
    """Without an API key, the xuanhuan fallback must surface 境界 markers."""

    result = XuanhuanConsultant(Settings()).draft_outline("废柴觉醒")
    assert all("境界" in ch for ch in result.chapters)


def test_romance_consultant_sends_romance_identity() -> None:
    fake_llm = _CapturingChat(_OUTLINE_PAYLOAD)
    consultant = RomanceConsultant(Settings())
    consultant._llm = fake_llm  # noqa: SLF001
    consultant._draft_outline_with_llm(  # noqa: SLF001
        idea="仇人之子",
        ideas=IdeasContext(),
    )

    systems = _system_texts(fake_llm.messages)
    assert any("言情题材" in text for text in systems)


def test_romance_consultant_uses_genre_fallback_when_no_llm() -> None:
    """Without an API key, the romance fallback must surface 节拍 markers."""

    result = RomanceConsultant(Settings()).draft_outline("仇人之子")
    assert all(ch.startswith("节拍") for ch in result.chapters)


def test_consultant_constructs_accept_prompt_registry_kwarg() -> None:
    """The constructor's ``prompt_registry`` kwarg is honoured."""

    from writer.prompts.registry import PromptRegistry, builtin_prompt_registry

    custom_registry = builtin_prompt_registry()
    consultant = StoryConsultant(Settings(), prompt_registry=custom_registry)
    assert consultant._prompt_registry is custom_registry  # noqa: SLF001

    # Default registry is created lazily
    other = StoryConsultant(Settings())
    assert isinstance(other._prompt_registry, PromptRegistry)  # noqa: SLF001
