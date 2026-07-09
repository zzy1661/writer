"""Tests for the long-form prose LLM client.

Added 2026-07-09 (real-writing-pipeline PR2) — covers the
:class:`LLMProseClient` Protocol contract, the
:class:`RealProseClient` LLM wrapper, the
:class:`DeterministicProseClient` offline path, the
:class:`LLMProseError` exception, and the production_deps selection
between Real and Deterministic based on ``settings.has_api_key``.

Tests for the production_deps selection live in
``test_engine_deps.py``; this file focuses on the prose module itself.
"""

from __future__ import annotations

from typing import Any

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from writer.llm.prose import (
    DeterministicProseClient,
    LLMProseClient,
    LLMProseError,
    RealProseClient,
)

# ---------------------------------------------------------------------------
# Test doubles
# ---------------------------------------------------------------------------


class _RecordingChatModel(BaseChatModel):
    """Fake ``BaseChatModel`` that records every ``invoke`` call.

    Returns a canned :class:`AIMessage` so ``RealProseClient`` can
    exercise the content-coercion path. Mirrors the recording-fake
    pattern documented in MEMORY.md ("BaseChatModel fake 测试需要").
    """

    last_messages: list = []  # type: ignore[type-arg]
    response_text: str = "ok"
    raise_on_invoke: Exception | None = None

    class Config:
        arbitrary_types_allowed = True

    @property
    def _llm_type(self) -> str:
        return "recording-fake"

    def _generate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        self.last_messages = list(messages)
        if self.raise_on_invoke is not None:
            raise self.raise_on_invoke
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=self.response_text))])

    async def _agenerate(  # type: ignore[override]
        self, messages, stop=None, run_manager=None, **kwargs: Any
    ) -> ChatResult:
        return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)


def _fake_prep_context(chapter_id: str, task: str, **kwargs: Any) -> Any:
    """Stub prep_context that returns a known pack shape.

    Avoids the real ``writer.context.prep_context`` import path so the
    tests stay offline and fast.
    """
    from dataclasses import dataclass

    @dataclass
    class Pack:
        system_block: str
        canon_block: str
        history_block: str
        task_block: str
        token_audit: dict[str, int]

    return Pack(
        system_block="system",
        canon_block=f"正典：{chapter_id} 的设定",
        history_block=f"前情：{task} 的历史",
        task_block="task",
        token_audit={},
    )


# ---------------------------------------------------------------------------
# Protocol contract
# ---------------------------------------------------------------------------


class TestLLMProseClientProtocol:
    def test_real_client_satisfies_protocol(self) -> None:
        client = RealProseClient(llm=_RecordingChatModel())
        assert isinstance(client, LLMProseClient)

    def test_deterministic_client_satisfies_protocol(self) -> None:
        client = DeterministicProseClient(prep_context_fn=_fake_prep_context)
        assert isinstance(client, LLMProseClient)

    def test_custom_subclass_satisfies_protocol(self) -> None:
        class _Custom:
            name = "custom"

            def generate_text(self, *, system: str, user: str) -> str:
                return "ok"

        assert isinstance(_Custom(), LLMProseClient)

    def test_name_attribute_is_a_string(self) -> None:
        client = DeterministicProseClient(prep_context_fn=_fake_prep_context)
        assert client.name == "deterministic"
        assert isinstance(client.name, str)

    def test_real_client_name_is_real(self) -> None:
        client = RealProseClient(llm=_RecordingChatModel())
        assert client.name == "real"


# ---------------------------------------------------------------------------
# RealProseClient
# ---------------------------------------------------------------------------


class TestRealProseClient:
    def test_generate_text_invokes_llm_once(self) -> None:
        llm = _RecordingChatModel(response_text="这是草稿")
        client = RealProseClient(llm=llm)
        result = client.generate_text(system="sys", user="usr")
        assert result == "这是草稿"
        assert len(llm.last_messages) == 2
        assert llm.last_messages[0].content == "sys"
        assert llm.last_messages[1].content == "usr"

    def test_generate_text_handles_list_content(self) -> None:
        llm = _RecordingChatModel()
        # Override the canned response with a list content.
        from langchain_core.outputs import ChatGeneration, ChatResult

        llm._generate = lambda messages, **kw: ChatResult(  # type: ignore[assignment]
            generations=[ChatGeneration(message=AIMessage(content=["part1", "part2"]))]
        )
        client = RealProseClient(llm=llm)
        result = client.generate_text(system="s", user="u")
        assert result == "part1\npart2"

    def test_generate_text_handles_dict_list_content(self) -> None:
        llm = _RecordingChatModel()
        from langchain_core.outputs import ChatGeneration, ChatResult

        llm._generate = lambda messages, **kw: ChatResult(
            generations=[
                ChatGeneration(
                    message=AIMessage(content=[{"text": "abc"}, {"text": "def"}])
                )
            ]
        )
        client = RealProseClient(llm=llm)
        assert client.generate_text(system="s", user="u") == "abc\ndef"

    def test_generate_text_raises_on_llm_error(self) -> None:
        llm = _RecordingChatModel(raise_on_invoke=RuntimeError("network down"))
        client = RealProseClient(llm=llm)
        with pytest.raises(LLMProseError) as excinfo:
            client.generate_text(system="s", user="u")
        assert "network down" in str(excinfo.value)

    def test_generate_text_raises_on_none_content(self) -> None:
        llm = _RecordingChatModel()
        from langchain_core.outputs import ChatGeneration, ChatResult

        llm._generate = lambda messages, **kw: ChatResult(
            generations=[ChatGeneration(message=AIMessage(content=None))]
        )
        client = RealProseClient(llm=llm)
        with pytest.raises(LLMProseError, match="None"):
            client.generate_text(system="s", user="u")

    def test_coerce_raises_on_unsupported_content_type(self) -> None:
        # Pydantic v2's AIMessage validator rejects non-{str, list}
        # content at construction time, so we cannot feed an
        # ``AIMessage(content=object())`` through ``RealProseClient``.
        # Instead, exercise the coercion helper directly via a tiny
        # stub that has the same ``.content`` shape — the helper
        # only reads ``.content`` so any object with that attribute
        # works.
        from writer.llm import prose as prose_module

        class _FakeMessage:
            content = object()

        with pytest.raises(LLMProseError, match="不支持"):
            prose_module._coerce_ai_message_to_text(_FakeMessage())

    def test_coerce_raises_on_none_content(self) -> None:
        from writer.llm import prose as prose_module

        class _FakeMessage:
            content = None

        with pytest.raises(LLMProseError, match="None"):
            prose_module._coerce_ai_message_to_text(_FakeMessage())

    def test_llm_prose_error_is_value_error(self) -> None:
        # Engine boundary catches ``Exception``, so subclasses of
        # ``ValueError`` get the same UX as a normal aborted turn.
        assert issubclass(LLMProseError, ValueError)


# ---------------------------------------------------------------------------
# DeterministicProseClient
# ---------------------------------------------------------------------------


class TestDeterministicProseClient:
    def test_default_prep_context_is_loaded_lazily(self) -> None:
        # Constructing a default DeterministicProseClient must NOT
        # eagerly import writer.context (which has heavy I/O at
        # construction time).
        client = DeterministicProseClient()
        assert client.prep_context_fn is not None

    def test_generate_text_is_at_least_200_chars(self) -> None:
        client = DeterministicProseClient(prep_context_fn=_fake_prep_context)
        result = client.generate_text(
            system="sys",
            user="chapter_id: 1.1\ntask: 测试",
        )
        assert len(result) >= 200, f"expected >= 200 chars, got {len(result)}"

    def test_generate_text_contains_chapter_heading(self) -> None:
        client = DeterministicProseClient(prep_context_fn=_fake_prep_context)
        result = client.generate_text(
            system="sys",
            user="chapter_id: 1.1\ntask: 测试本章",
        )
        assert "# 第 1.1 章" in result

    def test_generate_text_does_not_contain_placeholder(self) -> None:
        # The previous "正文占位" string must not appear in the
        # deterministic output. The placeholder is the most visible
        # regression marker for this PR.
        client = DeterministicProseClient(prep_context_fn=_fake_prep_context)
        result = client.generate_text(
            system="sys", user="chapter_id: 1.1\ntask: 测试",
        )
        assert "正文占位" not in result

    def test_generate_text_contains_canon_excerpt(self) -> None:
        client = DeterministicProseClient(prep_context_fn=_fake_prep_context)
        result = client.generate_text(
            system="sys", user="chapter_id: 1.1\ntask: 测试",
        )
        # The fake prep_context returns "正典: ..." in canon_block;
        # the deterministic output should include an excerpt.
        assert "正典" in result

    def test_generate_text_is_deterministic(self) -> None:
        client = DeterministicProseClient(prep_context_fn=_fake_prep_context)
        a = client.generate_text(system="s", user="chapter_id: 1.1\ntask: same")
        b = client.generate_text(system="s", user="chapter_id: 1.1\ntask: same")
        assert a == b

    def test_generate_text_handles_unknown_format(self) -> None:
        # When the user message is not in the expected format
        # ``chapter_id: ...\ntask: ...``, the client falls back to
        # ``("1.1", user)`` and still produces prose.
        client = DeterministicProseClient(prep_context_fn=_fake_prep_context)
        result = client.generate_text(system="s", user="随便写点")
        assert "# 第 1.1 章" in result
        assert len(result) >= 200

    def test_generate_text_uses_fake_prep_context(self) -> None:
        # When a fake prep_context is provided, the deterministic
        # client never touches the real ``writer.context.prep_context``.
        # The fake returns a known pack; verify the client uses the
        # canon_block from the fake.
        calls: list[tuple[str, str]] = []

        def spy_prep(chapter_id: str, task: str, **kwargs: Any) -> Any:
            calls.append((chapter_id, task))
            from dataclasses import dataclass

            @dataclass
            class Pack:
                system_block: str
                canon_block: str
                history_block: str
                task_block: str
                token_audit: dict[str, int]

            return Pack(
                system_block="",
                canon_block="FAKE_CANON",
                history_block="FAKE_HISTORY",
                task_block="",
                token_audit={},
            )

        client = DeterministicProseClient(prep_context_fn=spy_prep)
        result = client.generate_text(
            system="s", user="chapter_id: 2.3\ntask: testing"
        )
        assert calls == [("2.3", "testing")]
        assert "FAKE_CANON" in result
        assert "FAKE_HISTORY" in result
