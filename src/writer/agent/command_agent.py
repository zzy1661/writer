"""Rule-based dispatcher used as the ``WriterCommandAgent`` MVP.

This is a stable, network-free classifier that maps a REPL line to an
``AgentAction``. The real implementation (LangChain structured output,
per 备忘 15) will live behind the same ``WriterCommandAgent`` interface
so consumers and tests do not need to change.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

Role = Literal["story_consultant", "proofreader", "historian", "reviewer"]
ActionType = Literal[
    "run_command",
    "call_tool",
    "start_workflow",
    "ask_user",
    "answer_directly",
]


class AgentAction(BaseModel):
    """Decision returned by the command agent for a single user input.

    Only the fields relevant to ``action_type`` are populated; the rest
    stay at their defaults. Using ``BaseModel`` (not ``dataclass``) keeps
    JSON serialization cheap when we later swap in LLM structured output.
    """

    model_config = {"frozen": True}

    action_type: ActionType
    command: str | None = None
    role: Role | None = None
    workflow: str | None = None
    tool_name: str | None = None
    arguments: dict = Field(default_factory=dict)
    answer: str | None = None
    user_prompt: str | None = None


class WriterCommandAgent:
    """Rule-based dispatcher (MVP fallback)."""

    def decide(self, user_input: str, project_state: str) -> AgentAction:
        text = user_input.strip()

        if text.startswith("/写"):
            return AgentAction(
                action_type="start_workflow",
                command="/写",
                role="story_consultant",
                workflow="write_chapter",
                arguments={"raw": text},
            )
        if text.startswith("/审核"):
            return AgentAction(
                action_type="start_workflow",
                command="/审核",
                role="reviewer",
                workflow="review_chapter",
                arguments={"raw": text},
            )
        if "伏笔" in text or "F0" in text:
            return AgentAction(
                action_type="call_tool",
                role="story_consultant",
                tool_name="foreshadow_query",
                arguments={"query": text},
            )
        if text.startswith("/"):
            return AgentAction(
                action_type="run_command",
                command=text.split(maxsplit=1)[0],
            )

        return AgentAction(
            action_type="answer_directly",
            answer=(
                "我可以处理 /init、/大纲、/目录、/写、/审核、/改 等写作命令。"
                f"你刚才说的是：{text}"
            ),
        )


__all__ = [
    "ActionType",
    "AgentAction",
    "Role",
    "WriterCommandAgent",
]
