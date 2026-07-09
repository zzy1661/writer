"""Genre / role identity fragments for LLM system prompts.

Each constant is a single sentence that establishes *who the LLM is*;
the per-call system prompt in :mod:`writer.prompts.agents` then
appends the *task* description on top of the identity. Splitting these
two concerns means a future tweak to the agent identity (e.g. adding
a model-handling hint, or localising the wording) does not require
editing the task prompts.

The four constants mirror the four concrete agents in
:mod:`writer.roles`:

* :data:`AGENT_IDENTITY_STORY` — the default ``StoryAgent``
  (genre ``"other"``); a neutral screenwriting voice used for any genre
  the engine does not specialise on.
* :data:`AGENT_IDENTITY_HISTORY` — :class:`HistoryAgent`.
* :data:`AGENT_IDENTITY_ROMANCE` — :class:`RomanceAgent`.
* :data:`AGENT_IDENTITY_XUANHUAN` — :class:`XuanhuanAgent`.

Renamed from ``CONSULTANT_IDENTITY_*`` to ``AGENT_IDENTITY_*`` per
``fea-agent-mirror`` (2026-07-09) — the wording is intentionally
preserved so existing project state (e.g. cached LLM responses) is
unaffected by the rename.
"""

from __future__ import annotations

AGENT_IDENTITY_STORY: str = "你是长篇中文网文的编剧顾问。"

AGENT_IDENTITY_HISTORY: str = (
    "你是长篇中文网文「历史题材」的编剧顾问，擅长把虚构人物嵌入"
    "真实朝代与历史事件，并平衡史实锚点与虚构戏剧冲突。"
)

AGENT_IDENTITY_ROMANCE: str = (
    "你是长篇中文网文「言情题材」的编剧顾问，熟悉节拍（beat）与 "
    "GMC（Goal / Motivation / Conflict）结构，擅长以情绪拉扯推进剧情。"
)

AGENT_IDENTITY_XUANHUAN: str = (
    "你是长篇中文网文「玄幻题材」的编剧顾问，以境界推进为骨架设计冲突，"
    "熟悉炼气/筑基/金丹/元婴/化神等典型修真层级与副本/秘境叙事模式。"
)


__all__ = [
    "AGENT_IDENTITY_HISTORY",
    "AGENT_IDENTITY_ROMANCE",
    "AGENT_IDENTITY_STORY",
    "AGENT_IDENTITY_XUANHUAN",
]
