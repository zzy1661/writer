"""LLM system prompt 的题材 / 角色身份片段。

每个常量是一句建立「LLM 是谁」的话；:mod:`writer.prompts.agents` 中
每次调用的 system prompt 在身份之上再追加「任务」描述。把这两件
事分开，意味着未来调整 agent 身份（例如添加模型处理提示或本地化
措辞）时无需编辑任务 prompt。

四个常量对应 :mod:`writer.roles` 中四个具体 agent：

* :data:`AGENT_IDENTITY_STORY` —— 默认 ``StoryAgent``（题材
  ``"other"``）；中性的编剧口吻，用于引擎不专门化的任何题材。
* :data:`AGENT_IDENTITY_HISTORY` —— :class:`HistoryAgent`。
* :data:`AGENT_IDENTITY_ROMANCE` —— :class:`RomanceAgent`。
* :data:`AGENT_IDENTITY_XUANHUAN` —— :class:`XuanhuanAgent`。

按 ``fea-agent-mirror``（2026-07-09）从 ``CONSULTANT_IDENTITY_*``
重命名为 ``AGENT_IDENTITY_*`` —— 措辞刻意保持不变，让现有项目状态
（例如缓存的 LLM 响应）不受重命名影响。
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
