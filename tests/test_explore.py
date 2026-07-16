"""Tests for ``writer.explore`` multi-turn initialization."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest
from langchain_core.messages import AIMessage
from rich.console import Console

from writer.explore import ExploreOutcome, ExploreQuestion, run_explore


class _RecordingChatModel:
    def __init__(self, responses: list[str]) -> None:
        self.responses = iter(responses)
        self.messages: list[object] = []
        self.calls = 0

    def invoke(self, messages: object) -> AIMessage:
        self.calls += 1
        self.messages.append(messages)
        return AIMessage(content=next(self.responses))


class _PromptSession:
    def __init__(self, answers: list[str]) -> None:
        self.answers = iter(answers)

    def prompt(self, prompt: str) -> str:
        assert prompt == "> "
        return next(self.answers)


def _completed(*, architecture: str = "三幕结构") -> str:
    return (
        '{"status":"completed","outcome":'
        '{"core_idea":"# 核心创意\\n\\n完整故事核",'
        '"requirements":"- 篇幅: 长篇",'
        '"genres":["历史"],'
        f'"architecture":"{architecture}"}}}}'
    )


def _asking(question: str) -> str:
    return f'{{"status":"asking","question":"{question}"}}'


def test_run_explore_completes_when_llm_says_so() -> None:
    llm = _RecordingChatModel([_completed()])

    result = run_explore(
        "程序员穿越唐朝。",
        llm=llm,  # type: ignore[arg-type]
        console=Console(record=True),
        prompt_session=None,
    )

    assert result.architecture == "三幕结构"
    assert llm.calls == 1


def test_run_explore_handles_questions_then_complete() -> None:
    llm = _RecordingChatModel(
        [_asking("主角最想得到什么？"), _asking("他最害怕失去什么？"), _completed()]
    )

    result = run_explore(
        "一个穿越到唐朝的程序员。",
        llm=llm,  # type: ignore[arg-type]
        console=Console(record=True),
        prompt_session=_PromptSession(["改变官僚体系", "失去回家的机会"]),  # type: ignore[arg-type]
    )

    assert result.genres == ["历史"]
    assert llm.calls == 3
    assert len(llm.messages) == 3


def test_run_explore_synthesizes_when_budget_exhausted() -> None:
    llm = _RecordingChatModel([_asking(f"问题 {index}") for index in range(5)] + [_completed()])

    result = run_explore(
        "一个需要继续追问的故事。",
        llm=llm,  # type: ignore[arg-type]
        console=Console(record=True),
        prompt_session=_PromptSession(["回答"] * 5),  # type: ignore[arg-type]
    )

    assert result.brief_source == "budget_exhausted"
    assert llm.calls == 6


def test_run_explore_rejects_empty_brief() -> None:
    with pytest.raises(ValueError, match="创意描述不能为空"):
        run_explore(
            "  ",
            llm=_RecordingChatModel([]),  # type: ignore[arg-type]
            console=Console(record=True),
            prompt_session=None,
        )


def test_run_explore_uses_shipped_identity_and_architectures() -> None:
    llm = _RecordingChatModel([_completed()])

    run_explore(
        "一个故事。",
        llm=llm,  # type: ignore[arg-type]
        console=Console(record=True),
        prompt_session=None,
    )

    messages = llm.messages[0]
    system = "\n".join(message.content for message in messages)  # type: ignore[union-attr]
    assert "资深编剧" in system
    assert "雪花写作法" in system
    assert "单元串联架构" in system


def test_explore_outcome_dataclass_is_frozen() -> None:
    outcome = ExploreOutcome("# 核心", "- 篇幅: 长篇", ["历史"], "三幕结构")

    with pytest.raises(FrozenInstanceError):
        outcome.architecture = "英雄之旅"  # type: ignore[misc]


def test_explore_question_variants_validate() -> None:
    outcome = ExploreOutcome("# 核心", "- 篇幅: 长篇", ["历史"], "三幕结构")

    assert ExploreQuestion(status="asking", question="主角是谁？").status == "asking"
    assert ExploreQuestion(status="completed", outcome=outcome).outcome == outcome
    with pytest.raises(ValueError):
        ExploreQuestion(status="asking")
    with pytest.raises(ValueError):
        ExploreQuestion(status="completed")


def test_run_explore_exit_answer_raises_keyboard_interrupt() -> None:
    llm = _RecordingChatModel([_asking("还想补充什么？")])

    with pytest.raises(KeyboardInterrupt):
        run_explore(
            "一个故事。",
            llm=llm,  # type: ignore[arg-type]
            console=Console(record=True),
            prompt_session=_PromptSession(["/退出"]),  # type: ignore[arg-type]
        )


__all__ = []
