"""路由层：把用户输入映射为结构化 ``AgentAction``。

原先的名字 ``WriterCommandAgent``（位于 ``agent/command_agent.py``）让这个类
听起来像个完整的写作 agent，但实际上它只做一件事：把一行 REPL 输入
翻译成 ``AgentAction``。本模块通过引入下面两个概念把这一角色说清楚：

* :class:`IntentRouter` — 所有实现都满足的 ``Protocol`` 契约。
  引擎只依赖该 Protocol，不依赖任何具体类；未来实现
  （例如 LLM 支持的 ``LlmIntentRouter``）可以直接接入而无需改动
  ``engine/`` 或 ``cli/``。
* :class:`RuleBasedIntentRouter` — 当前 MVP。无网络的纯规则派发器，
  1:1 保留原 ``WriterCommandAgent.decide()`` 行为。

把 ``AgentAction`` 放在这里（而不是 ``agent/``）反映了分层：
``AgentAction`` 是 *路由的输出*，而不是任何业务 agent
（``StoryAgent``/``HistoryAgent``/``XuanhuanAgent``/``RomanceAgent`` 等）的属性。
引擎与消费者从 :mod:`writer.routing` 导入它。
"""

from __future__ import annotations

import re
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

Role = Literal["story_agent", "proofreader", "historian", "reviewer"]
ActionType = Literal[
    "run_command",
    "call_tool",
    "start_workflow",
    "ask_user",
    "answer_directly",
]


class AgentAction(BaseModel):
    """单个用户输入由 :class:`IntentRouter` 返回的决策。

    只有与 ``action_type`` 相关的字段会被填充，其余保持默认值。
    使用 ``BaseModel``（而非 ``dataclass``）让我们在后续把同一路由器背后
    换成 LLM 结构化输出实现时，JSON 序列化保持廉价。

    ``kind``（per ``fea-agent-mirror`` 增补）用于在 command 形态 action
    （``kind="command"``，默认 —— 填充 ``command`` / ``workflow`` /
    ``tool_name`` 等）和 agent 形态 action（``kind="agent"``，填充
    ``target_agent``）之间做区分。默认值保证所有现有调用点零差异。
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
    kind: Literal["command", "agent"] = "command"
    target_agent: str | None = None


@runtime_checkable
class IntentRouter(Protocol):
    """前台派发器：用户输入 → 结构化 ``AgentAction``。

    实现必须对输入保持确定性（无隐式副作用），让引擎在需要时可以确定性
    回放一轮。``project_state`` 参数为即将到来的 ``LlmIntentRouter``
    （LangChain 结构化输出，per 备忘 15）保留 —— 基于规则的 MVP
    故意忽略它。
    """

    def route(self, user_input: str, _project_state: str) -> AgentAction:
        ...


class RuleBasedIntentRouter:
    """无网络的规则派发器（MVP 回退）。"""

    # REPL 自身处理的框架级命令关键字，而非由路由器处理。
    # 列在此处以便 :meth:`looks_like_command` 在调用任何 LLM 之前
    # 就能短路掉它们。
    _FRAMEWORK_KEYWORDS: frozenset[str] = frozenset({"init", "状态", "退出", "帮助"})

    def route(self, user_input: str, _project_state: str) -> AgentAction:
        # ``_project_state`` 在此故意不使用；该参数的存在是为了当我们
        # 引入 :class:`LlmIntentRouter` 时保持 Protocol 稳定。
        # 下划线前缀表明该参数在本实现里仅占位。
        text = user_input.strip()

        if text.startswith("/字数统计"):
            path = _command_argument(text, "/字数统计") or "."
            return AgentAction(
                action_type="call_tool",
                command="/字数统计",
                role="story_agent",
                tool_name="wordcount",
                arguments={"path": path},
            )
        if text.startswith("/创作"):
            return AgentAction(
                action_type="start_workflow",
                command="/创作",
                role="story_agent",
                workflow="write_chapter",
                arguments={"raw": text},
            )
        if text.startswith("/骨架"):
            # per 2026-07-17 (chg-skeleton-chapters-pr1): ``/骨架`` 是 workflow
            # 命令,派发到 ``skeleton_chapters`` 工作流(per TODO/骨架命令.md §2).
            # 必须先于 ``/审核`` 分支(后者 catch-all ``startswith("/审核")``)与
            # 通用 ``text.startswith("/")`` fallback.
            return AgentAction(
                action_type="start_workflow",
                command="/骨架",
                role="story_agent",
                workflow="skeleton_chapters",
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
        # per 2026-07-17: ``/伏笔`` 是 shipped directive（所有题材共有）,
        # 必须先于 ``"伏笔" in text`` 子串匹配,否则 ``/伏笔 <描述>`` 会
        # 被误派到 ``foreshadow_search`` 工具（读 ``伏笔.yaml``）。本 directive
        # 是写 ``伏笔/伏笔表.md``,与 ``foreshadow_search`` 工具走的路径不同。
        if text.startswith("/伏笔"):
            return AgentAction(
                action_type="run_command",
                command="/伏笔",
                role="story_agent",
            )
        if "伏笔" in text or "F0" in text:
            return AgentAction(
                action_type="call_tool",
                role="story_agent",
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
                "我可以处理 /init、/start、/大纲、/目录、/人物、/骨架、/伏笔、/创作、/审核 等写作命令。"
                f"你刚才说的是：{text}"
            ),
        )

    @classmethod
    def looks_like_command(cls, text: str) -> bool:
        """当且仅当 ``text`` 应在不咨询 LLM 的情况下被处理时返回 True。

        由 :class:`writer.routing.CompositeRouter` 用来决定是否需要
        LLM 回退。故意保守：误报只多花一次 LLM 调用，漏报会破坏
        规则优先契约。
        """

        stripped = text.strip()
        if not stripped:
            return False
        if stripped.startswith("/"):
            return True
        # 裸框架关键字（例如 "退出", "状态"）
        return stripped in cls._FRAMEWORK_KEYWORDS


def _command_argument(text: str, command: str) -> str:
    """返回斜杠命令后的文本，去除首尾空白。"""

    return text.removeprefix(command).strip()


# ledger 条目 id 的模式（与 ``tools/builtin/foreshadow_ledger.py``
# 中的 schema 匹配）。规则抽取第一个 id 形态的 token，并以 ``id=...``
# 派发查询；剩余文本作为 ``keyword=...``，让子串过滤仍能捕获用户在
# id 旁边输入的描述性文字。
_FID_PATTERN = re.compile(r"\bF\d+\b")


def _parse_foreshadow_args(text: str) -> dict[str, Any]:
    """把自由形式的伏笔查询尽力拆分为工具参数。

    被 :class:`RuleBasedIntentRouter` 使用，让路由器产出结构化参数
    （``id`` / ``keyword``），而不是旧 RAG 工具消费的自由 ``query`` 字符串。
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
