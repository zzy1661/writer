"""LLM prompt centralization — the single source of truth for prompt text.

This package replaces the previous arrangement in which prompt strings
lived inline in :mod:`writer.routing.llm_router`,
:mod:`writer.project.ideas`, and :mod:`writer.roles.story_consultant`.
Centralizing them gives the rest of the system a single auditable
surface (useful when iterating on identity wording or A/B-testing
templates) and turns the four genre Consultants from hardcoded
subclasses into a single class with a ``GENRE`` discriminator.

Layering:

* :mod:`writer.prompts.protocol` — :class:`PromptKey` /
  :class:`PromptBundle` data types.
* :mod:`writer.prompts.identity` — short identity fragments per
  consultant (genre-agnostic wording about *who the LLM is*).
* :mod:`writer.prompts.router` — the ``COMMAND_AGENT_TEMPLATE`` used
  by :class:`writer.routing.LlmIntentRouter`.
* :mod:`writer.prompts.consultants` — the four outline templates, the
  TOC template, the init-brief template, and the deterministic
  :data:`FALLBACK_OUTLINE_CHAPTERS` chapter lists.
* :mod:`writer.prompts.shared` — the JSON-contract fallback for
  providers that do not support ``response_format``.
* :mod:`writer.prompts.registry` — the lookup surface, mirroring
  :mod:`writer.skills.registry.SkillRegistry`.
"""

from writer.prompts.consultants import (
    FALLBACK_OUTLINE_CHAPTERS,
    INIT_BRIEF_TEMPLATE,
    OUTLINE_TEMPLATE_HISTORY,
    OUTLINE_TEMPLATE_ROMANCE,
    OUTLINE_TEMPLATE_STORY,
    OUTLINE_TEMPLATE_XUANHUAN,
    TOC_TEMPLATE,
)
from writer.prompts.identity import (
    CONSULTANT_IDENTITY_HISTORY,
    CONSULTANT_IDENTITY_ROMANCE,
    CONSULTANT_IDENTITY_STORY,
    CONSULTANT_IDENTITY_XUANHUAN,
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
    "BUILTIN_PROMPTS",
    "COMMAND_AGENT_TEMPLATE",
    "CONSULTANT_IDENTITY_HISTORY",
    "CONSULTANT_IDENTITY_ROMANCE",
    "CONSULTANT_IDENTITY_STORY",
    "CONSULTANT_IDENTITY_XUANHUAN",
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
