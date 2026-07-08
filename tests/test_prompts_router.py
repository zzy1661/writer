"""Unit tests for :mod:`writer.prompts.router`."""

from __future__ import annotations

from writer.prompts.router import COMMAND_AGENT_TEMPLATE


def test_command_agent_template_has_system_message_with_boundaries() -> None:
    """The system message lists the action-type boundary the router must respect."""

    messages = COMMAND_AGENT_TEMPLATE.format_messages(
        project_state="S0",
        user_input="/init",
    )

    # First message is the system one
    system = messages[0]
    system_text = system.content if isinstance(system.content, str) else str(system.content)

    # The system message MUST mention the action-type boundaries that
    # the router is allowed to emit — this is the contract that
    # LlmIntentRouter relies on.
    assert "start_workflow" in system_text
    assert "call_tool" in system_text
    assert "ask_user" in system_text
    assert "answer_directly" in system_text


def test_command_agent_template_human_message_contains_state_and_input() -> None:
    """The human template must render ``project_state`` and ``user_input``."""

    messages = COMMAND_AGENT_TEMPLATE.format_messages(
        project_state="S3",
        user_input="帮我润色下这段",
    )

    # The second message carries the rendered values
    human = messages[1]
    human_text = human.content if isinstance(human.content, str) else str(human.content)

    assert "S3" in human_text
    assert "帮我润色下这段" in human_text
    assert "项目状态" in human_text


def test_command_agent_template_is_chat_prompt_template() -> None:
    """Sanity-check the public type — call sites rely on this."""

    from langchain_core.prompts import ChatPromptTemplate

    assert isinstance(COMMAND_AGENT_TEMPLATE, ChatPromptTemplate)
