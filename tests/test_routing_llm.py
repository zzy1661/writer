"""Unit tests for LlmIntentRouter and CompositeRouter."""

from __future__ import annotations

from pydantic import SecretStr

from writer.config import Settings
from writer.routing import (
    AgentAction,
    CompositeRouter,
    LlmIntentRouter,
    RuleBasedIntentRouter,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _settings(*, with_key: bool) -> Settings:
    return Settings(
        model="gpt-4o-mini",
        api_key=SecretStr("sk-test") if with_key else None,
        base_url="https://api.openai.com/v1",
        temperature=0.0,
    )


class _StubLLMRouter:
    """Minimal stand-in for LlmIntentRouter used to count invocations."""

    def __init__(self, responses: list[AgentAction] | None = None) -> None:
        self._responses = responses or [
            AgentAction(action_type="answer_directly", answer="stub")
        ]
        self.call_count = 0
        self.raise_on_next: Exception | None = None

    def route(self, user_input: str, project_state: str) -> AgentAction:
        self.call_count += 1
        if self.raise_on_next is not None:
            raise self.raise_on_next
        return self._responses[0]


# ---------------------------------------------------------------------------
# LlmIntentRouter
# ---------------------------------------------------------------------------


def test_llm_router_returns_structured_action() -> None:
    """LLM returns a JSON-encoded AgentAction; router parses it via with_structured_output."""
    from langchain_core.runnables import RunnableLambda

    expected = AgentAction(
        action_type="start_workflow",
        workflow="write_chapter",
        role="story_consultant",
        command="/创作",
    )
    chain = RunnableLambda(lambda _: expected)

    router = LlmIntentRouter(_settings(with_key=False), chain=chain)
    action = router.route("帮我写下一章", "S3")

    assert action.action_type == "start_workflow"
    assert action.workflow == "write_chapter"
    assert action.role == "story_consultant"


def test_llm_router_falls_back_on_validation_error() -> None:
    """When the LLM returns a malformed payload, CompositeRouter falls back to the rule router."""
    stub = _StubLLMRouter()
    stub.raise_on_next = ValueError("malformed JSON from model")

    primary = RuleBasedIntentRouter()
    composite = CompositeRouter(primary=primary, fallback=stub)  # type: ignore[arg-type]

    action = composite.route("帮我润色下这段", "S2")

    assert action.action_type == "answer_directly"
    assert stub.call_count == 1  # the LLM was attempted exactly once


# ---------------------------------------------------------------------------
# CompositeRouter rule-first behavior
# ---------------------------------------------------------------------------


def test_composite_router_uses_rule_first_for_slash_commands() -> None:
    stub = _StubLLMRouter()
    composite = CompositeRouter(
        primary=RuleBasedIntentRouter(), fallback=stub  # type: ignore[arg-type]
    )

    action = composite.route("/init", "S0")

    assert action.action_type == "run_command"
    assert action.command == "/init"
    assert stub.call_count == 0  # LLM not invoked


def test_composite_router_uses_rule_first_for_framework_keywords() -> None:
    stub = _StubLLMRouter()
    composite = CompositeRouter(
        primary=RuleBasedIntentRouter(), fallback=stub  # type: ignore[arg-type]
    )

    action = composite.route("退出", "S4")

    assert stub.call_count == 0
    # The bare keyword "退出" doesn't start with "/", so the rule router
    # falls through to the answer_directly template (which mentions the
    # command list). The point of this test is that the LLM was bypassed.
    assert action.action_type == "answer_directly"
    assert "退出" in (action.answer or "")


def test_composite_router_invokes_llm_for_natural_language() -> None:
    expected = AgentAction(
        action_type="start_workflow",
        workflow="write_chapter",
        role="story_consultant",
    )
    stub = _StubLLMRouter(responses=[expected])
    composite = CompositeRouter(
        primary=RuleBasedIntentRouter(), fallback=stub  # type: ignore[arg-type]
    )

    action = composite.route("帮我写下一章", "S3")

    assert action is expected
    assert stub.call_count == 1


def test_composite_router_deterministic_for_fixed_inputs() -> None:
    expected = AgentAction(action_type="answer_directly", answer="x")
    stub = _StubLLMRouter(responses=[expected])
    composite = CompositeRouter(
        primary=RuleBasedIntentRouter(), fallback=stub  # type: ignore[arg-type]
    )

    a1 = composite.route("你好", "S0")
    a2 = composite.route("你好", "S0")

    assert a1.model_dump() == a2.model_dump()


# ---------------------------------------------------------------------------
# RuleBasedIntentRouter.looks_like_command predicate
# ---------------------------------------------------------------------------


def test_looks_like_command_slash_prefix() -> None:
    assert RuleBasedIntentRouter.looks_like_command("/init")
    assert RuleBasedIntentRouter.looks_like_command("/创作 1.3")
    assert RuleBasedIntentRouter.looks_like_command("  /审核  ")


def test_looks_like_command_framework_keyword() -> None:
    assert RuleBasedIntentRouter.looks_like_command("退出")
    assert RuleBasedIntentRouter.looks_like_command("状态")


def test_looks_like_command_rejects_natural_language() -> None:
    assert not RuleBasedIntentRouter.looks_like_command("帮我润色下这段")
    assert not RuleBasedIntentRouter.looks_like_command("查一下 F003")
    assert not RuleBasedIntentRouter.looks_like_command("")
