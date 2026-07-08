"""Genre / role identity fragments for LLM system prompts.

Each constant is a single sentence that establishes *who the LLM is*;
the per-call system prompt in :mod:`writer.prompts.consultants` then
appends the *task* description on top of the identity. Splitting these
two concerns means a future tweak to the consultant identity (e.g. adding
a model-handling hint, or localising the wording) does not require
editing the task prompts.

The four constants mirror the four concrete consultants in
:mod:`writer.roles`:

* :data:`CONSULTANT_IDENTITY_STORY` — the default ``StoryConsultant``
  (genre ``"other"``); a neutral screenwriting voice used for any genre
  the engine does not specialise on.
* :data:`CONSULTANT_IDENTITY_HISTORY` — :class:`HistoryConsultant`.
* :data:`CONSULTANT_IDENTITY_ROMANCE` — :class:`RomanceConsultant`.
* :data:`CONSULTANT_IDENTITY_XUANHUAN` — :class:`XuanhuanConsultant`.
"""

from __future__ import annotations

CONSULTANT_IDENTITY_STORY: str = "你是长篇中文网文的编剧顾问。"

CONSULTANT_IDENTITY_HISTORY: str = (
    "你是长篇中文网文「历史题材」的编剧顾问，擅长把虚构人物嵌入"
    "真实朝代与历史事件，并平衡史实锚点与虚构戏剧冲突。"
)

CONSULTANT_IDENTITY_ROMANCE: str = (
    "你是长篇中文网文「言情题材」的编剧顾问，熟悉节拍（beat）与 "
    "GMC（Goal / Motivation / Conflict）结构，擅长以情绪拉扯推进剧情。"
)

CONSULTANT_IDENTITY_XUANHUAN: str = (
    "你是长篇中文网文「玄幻题材」的编剧顾问，以境界推进为骨架设计冲突，"
    "熟悉炼气/筑基/金丹/元婴/化神等典型修真层级与副本/秘境叙事模式。"
)


__all__ = [
    "CONSULTANT_IDENTITY_HISTORY",
    "CONSULTANT_IDENTITY_ROMANCE",
    "CONSULTANT_IDENTITY_STORY",
    "CONSULTANT_IDENTITY_XUANHUAN",
]
