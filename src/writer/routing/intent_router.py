"""Routing layer: maps user input to a structured ``AgentAction``.

The previous name ``WriterCommandAgent`` (in ``agent/command_agent.py``) made the
class sound like a full writing agent, but it actually only does one thing:
translate a REPL line into an ``AgentAction``. This module makes that role
explicit by introducing:

* :class:`IntentRouter` — the ``Protocol`` contract every implementation
  satisfies. The engine depends on this Protocol only, not on any concrete
  class, so future implementations (e.g. an LLM-backed
  ``LlmIntentRouter``) plug in without touching ``engine/`` or ``cli/``.
* :class:`RuleBasedIntentRouter` — the current MVP. Network-free, pure rule
  dispatcher that preserves the behavior of the original
  ``WriterCommandAgent.decide()`` 1:1.

Keeping ``AgentAction`` here (instead of in ``agent/``) reflects the layering:
``AgentAction`` is the **output of routing**, not a property of any business
agent (``NovelAgent``/``StoryConsultant`` etc.). Engines and consumers import
it from :mod:`writer.routing`.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Protocol, runtime_checkable

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
    """Decision returned by an :class:`IntentRouter` for a single user input.

    Only the fields relevant to ``action_type`` are populated; the rest stay
    at their defaults. Using ``BaseModel`` (not ``dataclass``) keeps JSON
    serialization cheap when we later swap in an LLM structured-output
    implementation behind the same router.
    """

    model_config = {"frozen": True}

    action_type: ActionType
    command: str | None = None
    role: Role | None = None
    workflow: str | None = None
    tool_name: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    answer: str | None = None
    user_prompt: str | None = None


@runtime_checkable
class IntentRouter(Protocol):
    """Front-desk dispatcher: user input → structured ``AgentAction``.

    Implementations must be deterministic w.r.t. their inputs (no implicit
    side effects) so the engine can replay a turn deterministically when
    needed. The ``project_state`` parameter is reserved for the upcoming
    ``LlmIntentRouter`` (LangChain structured output, per 备忘 15) — the
    rule-based MVP ignores it on purpose.
    """

    def route(self, user_input: str, project_state: str) -> AgentAction:
        ...


class RuleBasedIntentRouter:
    """Network-free rule dispatcher (MVP fallback)."""

    # Framework-level command keywords handled by REPL itself, not by the
    # router. Listed here so :meth:`looks_like_command` can short-circuit
    # them before any LLM call.
    _FRAMEWORK_KEYWORDS: frozenset[str] = frozenset({"init", "状态", "退出", "帮助"})

    def route(self, user_input: str, project_state: str) -> AgentAction:
        # ``project_state`` is intentionally unused here; the parameter
        # exists so the Protocol stays stable when we add
        # :class:`LlmIntentRouter`. Deleting it (vs. renaming to
        # ``_project_state``) keeps the public signature aligned with the
        # docs without changing router-call sites.
        del project_state

        text = user_input.strip()

        if text.startswith("/查看"):
            path = _command_argument(text, "/查看") or "."
            tool_name = "safe_list_dir" if path in {".", "./"} or path.endswith("/") else "safe_read_file"
            return AgentAction(
                action_type="call_tool",
                command="/查看",
                role="story_consultant",
                tool_name=tool_name,
                arguments={"path": path},
            )
        if text.startswith("/搜索"):
            query = _command_argument(text, "/搜索")
            return AgentAction(
                action_type="call_tool",
                command="/搜索",
                role="story_consultant",
                tool_name="project_search",
                arguments={"query": query, "path": "."},
            )
        if text.startswith("/字数统计"):
            path = _command_argument(text, "/字数统计") or "."
            return AgentAction(
                action_type="call_tool",
                command="/字数统计",
                role="story_consultant",
                tool_name="wordcount",
                arguments={"path": path},
            )
        if text.startswith("/创作"):
            return AgentAction(
                action_type="start_workflow",
                command="/创作",
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
                tool_name="foreshadow_search",
                arguments=_parse_foreshadow_args(text),
            )
        if text.startswith("/"):
            return AgentAction(
                action_type="run_command",
                command=text.split(maxsplit=1)[0],
            )

        return AgentAction(
            action_type="answer_directly",
            answer=(
                "我可以处理 /init、/大纲、/目录、/创作、/审核、/改 等写作命令。"
                f"你刚才说的是：{text}"
            ),
        )

    @classmethod
    def looks_like_command(cls, text: str) -> bool:
        """Return True iff ``text`` should be handled without consulting an LLM.

        Used by :class:`writer.routing.CompositeRouter` to decide whether
        the LLM fallback is necessary. Conservative on purpose: false
        positives cost one LLM call, false negatives break the rule-first
        contract.
        """

        stripped = text.strip()
        if not stripped:
            return False
        if stripped.startswith("/"):
            return True
        # Bare framework keyword (e.g. "退出", "状态")
        return stripped in cls._FRAMEWORK_KEYWORDS


def _command_argument(text: str, command: str) -> str:
    """Return the text after a slash command, stripped of surrounding space."""

    return text.removeprefix(command).strip()


# Pattern for ledger entry ids (matches the schema in
# ``tools/builtin/foreshadow_ledger.py``). The rule extracts the first
# id-looking token and routes the query with ``id=...``; the remainder
# of the text becomes ``keyword=...`` so the substring filter still
# catches descriptive text the user typed alongside the id.
_FID_PATTERN = re.compile(r"\bF\d+\b")


def _parse_foreshadow_args(text: str) -> dict[str, Any]:
    """Best-effort split of a free-form foreshadow query into tool args.

    Used by :class:`RuleBasedIntentRouter` so the router emits
    structured args (``id`` / ``keyword``) instead of the legacy
    free-form ``query`` string the old RAG-based tool consumed.
    """

    stripped = text.strip()
    match = _FID_PATTERN.search(stripped)
    if match is None:
        return {"keyword": stripped}
    return {"id": match.group(0), "keyword": stripped}


__all__ = [
    "ActionType",
    "AgentAction",
    "IntentRouter",
    "Role",
    "RuleBasedIntentRouter",
]
