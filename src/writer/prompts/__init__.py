"""LLM prompt centralization — the single source of truth for prompt text.

This package replaces the previous arrangement in which prompt strings
lived inline in :mod:`writer.routing.llm_router`,
:mod:`writer.project.ideas`, and :mod:`writer.roles.story_agent`.
Centralizing them gives the rest of the system a single auditable
surface (useful when iterating on identity wording or A/B-testing
templates) and turns the four genre Agents from hardcoded
subclasses into a single class with a ``GENRE`` discriminator.

Layering:

* :mod:`writer.prompts.protocol` — :class:`PromptKey` /
  :class:`PromptBundle` data types.
* :mod:`writer.prompts.identity` — short identity fragments per
  agent (genre-agnostic wording about *who the LLM is*).
* :mod:`writer.prompts.router` — the ``COMMAND_AGENT_TEMPLATE`` used
  by :class:`writer.routing.LlmIntentRouter`.
* :mod:`writer.prompts.agents` — the four outline templates, the
  TOC template, the init-brief template, and the deterministic
  :data:`FALLBACK_OUTLINE_CHAPTERS` chapter lists.
* :mod:`writer.prompts.shared` — the JSON-contract fallback for
  providers that do not support ``response_format``.
* :mod:`writer.prompts.registry` — the lookup surface, mirroring
  :mod:`writer.skills.registry.SkillRegistry`.

Renamed from ``consultants`` to ``agents`` per ``fea-agent-mirror``
(2026-07-09); clean break — no ``CONSULTANT_IDENTITY_*`` aliases are
preserved.
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
