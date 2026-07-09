"""LLM prompt 集中化 —— prompt 文本的单一真理来源。

本包取代了原先的安排 —— prompt 字符串曾分散在
:mod:`writer.routing.llm_router`、:mod:`writer.project.ideas` 和
:mod:`writer.roles.story_agent` 中。集中化让系统的其余部分拥有
单一可审计的表面（迭代身份措辞或 A/B 测试模板时很有用），并把
四个题材 Agent 从硬编码子类转变为带 ``GENRE`` 鉴别器的单一类。

分层：

* :mod:`writer.prompts.protocol` —— :class:`PromptKey` /
  :class:`PromptBundle` 数据类型。
* :mod:`writer.prompts.context` —— :class:`ContextPack` 与
  :func:`prep_context`，负责章节级 prompt 素材组装。
* :mod:`writer.prompts.identity` —— 每个 agent 的短身份片段
  （关于「LLM 是谁」的与题材无关措辞）。
* :mod:`writer.prompts.router` —— 被 :class:`writer.routing.LlmIntentRouter`
  使用的 ``COMMAND_AGENT_TEMPLATE``。
* :mod:`writer.prompts.agents` —— 四个大纲模板、TOC 模板、
  init-brief 模板，以及确定性的 :data:`FALLBACK_OUTLINE_CHAPTERS`
  章节目录。
* :mod:`writer.prompts.shared` —— 不支持 ``response_format`` 的
  provider 的 JSON 契约回退。
* :mod:`writer.prompts.registry` —— 查找表面，镜像
  :mod:`writer.skills.registry.SkillRegistry`。

按 ``fea-agent-mirror``（2026-07-09）从 ``consultants`` 重命名为
``agents``；干净切割 —— 不保留 ``CONSULTANT_IDENTITY_*`` 别名。
"""

from writer.prompts.agents import (
    FALLBACK_OUTLINE_CHAPTERS,
    INIT_BRIEF_TEMPLATE,
    OUTLINE_TEMPLATE_HISTORY,
    OUTLINE_TEMPLATE_ROMANCE,
    OUTLINE_TEMPLATE_STORY,
    OUTLINE_TEMPLATE_XUANHUAN,
    TOC_TEMPLATE,
)
from writer.prompts.identity import (
    AGENT_IDENTITY_HISTORY,
    AGENT_IDENTITY_ROMANCE,
    AGENT_IDENTITY_STORY,
    AGENT_IDENTITY_XUANHUAN,
)
from writer.prompts.protocol import PromptBundle, PromptKey
from writer.prompts.registry import (
    BUILTIN_PROMPTS,
    ENTRY_POINT_GROUP,
    PromptRegistry,
    PromptRegistryError,
    built_prompt_registry,
    builtin_prompt_registry,
    discover_entry_point_prompts,
)
from writer.prompts.router import COMMAND_AGENT_TEMPLATE
from writer.prompts.shared import json_contract_message

__all__ = [
    "AGENT_IDENTITY_HISTORY",
    "AGENT_IDENTITY_ROMANCE",
    "AGENT_IDENTITY_STORY",
    "AGENT_IDENTITY_XUANHUAN",
    "BUILTIN_PROMPTS",
    "COMMAND_AGENT_TEMPLATE",
    "ENTRY_POINT_GROUP",
    "FALLBACK_OUTLINE_CHAPTERS",
    "INIT_BRIEF_TEMPLATE",
    "OUTLINE_TEMPLATE_HISTORY",
    "OUTLINE_TEMPLATE_ROMANCE",
    "OUTLINE_TEMPLATE_STORY",
    "OUTLINE_TEMPLATE_XUANHUAN",
    "PromptBundle",
    "PromptKey",
    "PromptRegistry",
    "PromptRegistryError",
    "TOC_TEMPLATE",
    "built_prompt_registry",
    "builtin_prompt_registry",
    "discover_entry_point_prompts",
    "json_contract_message",
]
