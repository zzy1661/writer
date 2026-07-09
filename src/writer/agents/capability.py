"""Agent capabilities — Python-side helpers the LLM does not directly perform.

The Markdown-paradigm agent system (``writer.agents.AgentRegistry`` /
``writer.agents.Agent``) ships *identity* (the agent's system prompt for
LLM dispatch). It does **not** ship *capabilities* (the deterministic
Python helpers that run before/after an LLM call, file writes,
structured-output parsing, etc.). This module collects those Python-side
helpers so the "Agent" concept has a single semantic home — both the
Markdown identity layer and the deterministic Python capability layer
live in :mod:`writer.agents`.

The original capability surface (``StoryAgent`` / ``HistoryAgent` /
``XuanhuanAgent` / ``RomanceAgent``) was deleted in the
``chg-remove-roles`` cleanup because every method except
:func:`process_init_brief` was dead code after ``fea-agent-mirror``
moved the LLM-facing identity to Markdown. The remaining helper is
exposed as a free function rather than a class because:

* It has no stateful resources — ``Settings`` and ``BaseChatModel`` are
  passed as call arguments.
* It does not branch by ``genre`` (the prompt template and schema are
  genre-agnostic; per-genre specialisation is handled by Markdown
  agents).
* The ``LLMToolLoop``-style class survives only because it loops and
  owns state; this function does neither.

Public surface (per ``chg-remove-roles``):

* :class:`InitBriefResult` — frozen dataclass for the post-init brief.
* :func:`process_init_brief` — the only Python-side helper kept after
  the ``roles`` package deletion.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from pydantic import BaseModel, Field

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from writer.config import Settings

log = logging.getLogger(__name__)


class _InitBriefPayload(BaseModel):
    """Pydantic schema for ``process_init_brief`` LLM structured output."""

    core_idea: str = Field(min_length=1)
    requirements: str = Field(min_length=1)


@dataclass(frozen=True)
class InitBriefResult:
    """Structured output for the post-init creative brief.

    Fields:
        core_idea: Markdown body for ``创意/核心创意.md`` (string).
        requirements: Markdown list appended to ``AGENT.md``'s
            ``## 基本要求`` section.
        source: ``"llm"`` when the structured-output path succeeded,
            ``"fallback"`` when the LLM is unavailable / fails.
    """

    core_idea: str
    requirements: str
    source: str = "fallback"


def _process_init_brief_fallback(brief: str) -> InitBriefResult:
    """Offline-mode init brief — used when no API key is configured."""

    return InitBriefResult(
        core_idea=(
            f"# 核心创意\n\n"
            f"{brief}\n\n"
            "## 扩写\n\n"
            "（离线模式：请配置 WRITER_API_KEY 后重新运行 init 以获得 LLM 扩写。）\n"
        ),
        requirements=(
            f"- 用户原始描述: {brief}\n"
            "- 篇幅目标: 20–50 万字长篇\n"
            "- 风格: 中文网文\n"
        ),
        source="fallback",
    )


def _process_init_brief_with_llm(
    brief: str,
    settings: Settings,
    llm: BaseChatModel,
) -> InitBriefResult:
    """LLM-backed init brief — uses the centralised prompt registry.

    Lazy imports keep :mod:`writer.llm` and :mod:`writer.prompts` from
    dragging in their full stack at engine import time (rule-only
    deployments never need either).
    """

    from writer.llm import get_llm, invoke_structured_json
    from writer.prompts import PromptKey, builtin_prompt_registry

    llm = llm or get_llm(settings)
    registry = builtin_prompt_registry()
    bundle = registry.require(PromptKey(role="init_brief"))
    messages = bundle.template.format_messages(brief=brief)
    payload = invoke_structured_json(llm, messages, _InitBriefPayload)

    core = payload.core_idea.strip()
    reqs = payload.requirements.strip()
    if not core.startswith("#"):
        core = f"# 核心创意\n\n{core}"
    return InitBriefResult(core_idea=core + "\n", requirements=reqs, source="llm")


def process_init_brief(
    brief: str,
    *,
    settings: Settings,
    llm: BaseChatModel | None = None,
) -> InitBriefResult:
    """Expand a natural-language brief into the project's ``InitBriefResult``.

    Behaviour:

    * Empty / whitespace-only ``brief`` → ``ValueError``.
    * API key configured (or ``llm=`` injected) → invoke the LLM with the
      ``init_brief`` prompt template; fall back to deterministic Markdown
      on any LLM-side failure (logged at WARNING).
    * No API key → deterministic Markdown.

    This helper is the **only** Python-side capability that survives the
    ``chg-remove-roles`` cleanup. ``outline`` / ``toc`` drafting is no
    longer a Python helper — it is executed by the LLM consuming
    ``writer/agents/_shipped/*.md`` identity (see
    ``writer/skills/_shipped/大纲/SKILL.md`` for instructions).
    """

    normalized = brief.strip()
    if not normalized:
        msg = "创意描述不能为空。"
        raise ValueError(msg)

    if settings.has_api_key or llm is not None:
        try:
            return _process_init_brief_with_llm(normalized, settings, llm)  # type: ignore[arg-type]
        except Exception as exc:  # noqa: BLE001 — role must degrade gracefully
            log.warning(
                "LLM init brief 失败，回退到本地摘要: %r", exc, exc_info=True
            )
    return _process_init_brief_fallback(normalized)


__all__ = ["InitBriefResult", "process_init_brief"]
