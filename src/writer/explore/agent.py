"""``/init`` explore 模式的多轮对话能力。"""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import TYPE_CHECKING, Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from pydantic import BaseModel, Field, model_validator
from rich.console import Console

from writer.explore.architectures import ARCHITECTURES
from writer.explore.prompts import EXPLORE_SYSTEM_TEMPLATE
from writer.llm.structured import invoke_structured_json

if TYPE_CHECKING:
    from prompt_toolkit import PromptSession


MAX_EXPLORE_QUESTIONS = 5


@dataclass(frozen=True)
class ExploreOutcome:
    """explore 模式的最终产出。

    ``core_idea`` 直接写入 ``创意/核心创意.md``；``requirements`` 追加到
    ``AGENT.md`` 的 ``## 基本要求`` 段。``brief_source`` 用于区分正常收尾
    与五轮提问预算耗尽后的综合收尾。
    """

    core_idea: str
    requirements: str
    genres: list[str]
    architecture: str
    brief_source: str = "llm"


class ExploreQuestion(BaseModel):
    """LLM 单轮响应的结构化契约。"""

    status: Literal["asking", "completed"]
    question: str | None = Field(default=None, min_length=1)
    outcome: ExploreOutcome | None = None

    @model_validator(mode="after")
    def _validate_variant(self) -> ExploreQuestion:
        if self.status == "asking":
            if self.question is None:
                raise ValueError("asking 响应必须包含 question")
            if self.outcome is not None:
                raise ValueError("asking 响应不能包含 outcome")
        elif self.outcome is None:
            raise ValueError("completed 响应必须包含 outcome")
        elif self.question is not None:
            raise ValueError("completed 响应不能包含 question")
        return self


def _architectures_markdown() -> str:
    return "\n\n".join(spec.markdown.rstrip() for spec in ARCHITECTURES)


def _read_answer(prompt_session: PromptSession[str] | None) -> str:
    if prompt_session is not None:
        return prompt_session.prompt("> ")
    return input("> ")


def _is_exit_answer(answer: str) -> bool:
    return answer.strip().lower() in {"/退出", "exit", "q"}


def _append_ai_response(messages: list[BaseMessage], response: ExploreQuestion) -> None:
    messages.append(AIMessage(content=response.model_dump_json()))


def _synthesize_outcome_from_messages(
    messages: list[BaseMessage],
    llm: BaseChatModel,
) -> ExploreOutcome:
    """在提问预算耗尽后，要求模型基于完整上下文做一次强制收尾。"""

    synthesis_messages = [
        *messages,
        HumanMessage(
            content=(
                "提问预算已耗尽。请停止提问，基于以上完整对话直接输出 status=completed，"
                "并填写完整的 outcome（core_idea、requirements、genres、architecture）。"
            )
        ),
    ]
    response = invoke_structured_json(llm, synthesis_messages, ExploreQuestion)
    if response.status != "completed" or response.outcome is None:
        raise ValueError("explore 收尾响应未提供 completed outcome")
    return replace(response.outcome, brief_source="budget_exhausted")


def run_explore(
    brief: str,
    *,
    llm: BaseChatModel,
    console: Console,
    prompt_session: PromptSession[str] | None,
    max_questions: int = MAX_EXPLORE_QUESTIONS,
) -> ExploreOutcome:
    """围绕初始梗概运行最多 ``max_questions`` 轮合作式探索。"""

    normalized = brief.strip()
    if not normalized:
        raise ValueError("创意描述不能为空。")

    messages = list(
        EXPLORE_SYSTEM_TEMPLATE.format_messages(
            brief=normalized,
            architectures_markdown=_architectures_markdown(),
        )
    )

    for _ in range(max_questions):
        response = invoke_structured_json(llm, messages, ExploreQuestion)
        if response.status == "completed" and response.outcome is not None:
            return response.outcome

        # ``ExploreQuestion`` 的校验器已保证 asking 分支有 question。
        assert response.question is not None
        console.print(f"[cyan]writer? {response.question}[/cyan]")
        answer = _read_answer(prompt_session)
        if _is_exit_answer(answer):
            raise KeyboardInterrupt
        _append_ai_response(messages, response)
        messages.append(HumanMessage(content=answer))

    return _synthesize_outcome_from_messages(messages, llm)


__all__ = [
    "MAX_EXPLORE_QUESTIONS",
    "ExploreOutcome",
    "ExploreQuestion",
    "run_explore",
]
