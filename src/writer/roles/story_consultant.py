"""Story Consultant role — the screenwriting specialist.

This is one *role* in the agent system (per 备忘 04 / 16 / 17), alongside
others that will land later (``proofreader``, ``historian``, ``reviewer``).
A role exposes a small capability surface — currently
:meth:`StoryConsultant.draft_outline` — that the engine, CLI, and workflow
stubs call explicitly. Roles do not invoke each other directly; cross-role
composition happens at the workflow graph layer.

When an API key is configured, the default consultant asks the configured
LLM for a structured outline. Without a key (or if the provider fails), it
falls back to the deterministic four-act outline so the CLI remains usable
offline.

Genre dispatch lives on the ``GENRE`` class attribute. Subclasses
(``HistoryConsultant`` / ``RomanceConsultant`` / ``XuanhuanConsultant``)
override ``GENRE`` only; the parent's
:meth:`StoryConsultant._draft_outline_with_llm` looks the prompt up via
``self._prompt_registry.require(PromptKey(role="outline", genre=self.GENRE))``
so each genre gets the matching identity fragment without re-implementing
the dispatch logic.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from langchain_core.language_models import BaseChatModel
from pydantic import BaseModel, Field

from writer.config import Settings
from writer.llm import get_llm
from writer.llm.structured import invoke_structured_json
from writer.project.ideas import (
    IdeasContext,
    build_outline_user_message,
    load_ideas_context,
)
from writer.prompts import (
    FALLBACK_OUTLINE_CHAPTERS,
    PromptKey,
    PromptRegistry,
    builtin_prompt_registry,
)

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutlineResult:
    """A lightweight outline response for the initial CLI workflow."""

    title: str
    premise: str
    chapters: list[str]
    source: str = "fallback"


@dataclass(frozen=True)
class TocResult:
    """A lightweight table-of-contents response for the /目录 command."""

    title: str
    chapters: list[str]


class _OutlinePayload(BaseModel):
    title: str = Field(min_length=1)
    premise: str
    chapters: list[str] = Field(min_length=4)


class _TocPayload(BaseModel):
    title: str = Field(min_length=1)
    chapters: list[str] = Field(min_length=4)


class _InitBriefPayload(BaseModel):
    core_idea: str = Field(min_length=1)
    requirements: str = Field(min_length=1)


@dataclass(frozen=True)
class InitBriefResult:
    """Structured output for the post-init creative brief."""

    core_idea: str
    requirements: str
    source: str = "fallback"


class StoryConsultant:
    """Screenwriting consultant — drafts four-act outlines from a premise.

    Subclasses set ``GENRE`` to dispatch the prompt lookup
    (e.g. ``HistoryConsultant.GENRE = "历史"``). The parent's
    ``_draft_outline_with_llm`` looks up
    ``PromptKey(role="outline", genre=self.GENRE)`` so a single
    implementation drives all four genres.
    """

    GENRE: ClassVar[str] = "other"

    def __init__(
        self,
        settings: Settings,
        *,
        llm: BaseChatModel | None = None,
        prompt_registry: PromptRegistry | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm
        self._prompt_registry = prompt_registry or builtin_prompt_registry()

    def draft_outline(
        self,
        idea: str,
        *,
        project_root: Path | None = None,
    ) -> OutlineResult:
        normalized_idea = idea.strip()
        ideas = load_ideas_context(project_root)
        if self._settings.has_api_key or self._llm is not None:
            try:
                return self._draft_outline_with_llm(normalized_idea, ideas)
            except Exception as exc:  # noqa: BLE001 — role must degrade gracefully
                log.warning("LLM 大纲生成失败,回退到本地四幕大纲: %r", exc, exc_info=True)
        return self._draft_outline_fallback(normalized_idea, ideas)

    def draft_toc(self, outline_text: str) -> TocResult:
        normalized = outline_text.strip()
        if not normalized:
            msg = "大纲内容为空，无法生成目录。"
            raise ValueError(msg)
        if self._settings.has_api_key or self._llm is not None:
            try:
                return self._draft_toc_with_llm(normalized)
            except Exception as exc:  # noqa: BLE001 — role must degrade gracefully
                log.warning("LLM 目录生成失败,回退到本地章节目录: %r", exc, exc_info=True)
        return self._draft_toc_fallback(normalized)

    def process_init_brief(self, brief: str) -> InitBriefResult:
        normalized = brief.strip()
        if not normalized:
            msg = "创意描述不能为空。"
            raise ValueError(msg)
        if self._settings.has_api_key or self._llm is not None:
            try:
                return self._process_init_brief_with_llm(normalized)
            except Exception as exc:  # noqa: BLE001 — role must degrade gracefully
                log.warning("LLM init brief 失败,回退到本地摘要: %r", exc, exc_info=True)
        return self._process_init_brief_fallback(normalized)

    def _process_init_brief_fallback(self, brief: str) -> InitBriefResult:
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

    def _process_init_brief_with_llm(self, brief: str) -> InitBriefResult:
        llm = self._llm or get_llm(self._settings)
        bundle = self._prompt_registry.require(PromptKey(role="init_brief"))
        messages = bundle.template.format_messages(brief=brief)
        payload = invoke_structured_json(llm, messages, _InitBriefPayload)
        core = payload.core_idea.strip()
        reqs = payload.requirements.strip()
        if not core.startswith("#"):
            core = f"# 核心创意\n\n{core}"
        return InitBriefResult(core_idea=core + "\n", requirements=reqs, source="llm")

    def _draft_outline_fallback(
        self,
        normalized_idea: str,
        ideas: IdeasContext,
    ) -> OutlineResult:
        premise = normalized_idea
        if not premise and ideas.core_idea:
            premise = ideas.core_idea
        title = self._build_working_title(premise)

        chapters = FALLBACK_OUTLINE_CHAPTERS.get(
            self.GENRE, FALLBACK_OUTLINE_CHAPTERS["other"]
        )
        return OutlineResult(
            title=title,
            premise=premise,
            chapters=chapters,
            source="fallback",
        )

    def _draft_outline_with_llm(self, idea: str, ideas: IdeasContext) -> OutlineResult:
        llm = self._llm or get_llm(self._settings)
        bundle = self._prompt_registry.require(
            PromptKey(role="outline", genre=self.GENRE)
        )
        user_message = build_outline_user_message(
            user_instruction=idea,
            ideas=ideas,
        )
        messages = bundle.template.format_messages(user_message=user_message)
        payload = invoke_structured_json(llm, messages, _OutlinePayload)
        chapters = [chapter.strip() for chapter in payload.chapters if chapter.strip()]
        if len(chapters) < 4:
            msg = "LLM 大纲章节少于 4 条"
            raise ValueError(msg)
        return OutlineResult(
            title=payload.title.strip(),
            premise=payload.premise.strip(),
            chapters=chapters,
            source="llm",
        )

    def _draft_toc_fallback(self, outline_text: str) -> TocResult:
        title = self._extract_outline_title(outline_text)
        act_lines = [
            line.strip().lstrip("- ").strip()
            for line in outline_text.splitlines()
            if line.strip().startswith("- ")
        ]
        if not act_lines:
            act_lines = [
                "第一幕：起",
                "第二幕：承",
                "第三幕：转",
                "第四幕：合",
            ]

        chapters: list[str] = []
        for index, act in enumerate(act_lines, start=1):
            chapters.append(f"第{index * 3 - 2}章 {act} · 开端")
            chapters.append(f"第{index * 3 - 1}章 {act} · 冲突")
            chapters.append(f"第{index * 3}章 {act} · 收束")
        return TocResult(title=title, chapters=chapters)

    def _draft_toc_with_llm(self, outline_text: str) -> TocResult:
        llm = self._llm or get_llm(self._settings)
        bundle = self._prompt_registry.require(PromptKey(role="toc"))
        messages = bundle.template.format_messages(outline_text=outline_text)
        payload = invoke_structured_json(llm, messages, _TocPayload)
        chapters = [chapter.strip() for chapter in payload.chapters if chapter.strip()]
        if len(chapters) < 4:
            msg = "LLM 目录章节少于 4 条"
            raise ValueError(msg)
        return TocResult(
            title=payload.title.strip(),
            chapters=chapters,
        )

    def _extract_outline_title(self, outline_text: str) -> str:
        for line in outline_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("# "):
                return stripped.removeprefix("# ").strip() or "未命名长篇小说"
        compact = outline_text.replace("\n", " ").strip()
        return compact[:18] + ("..." if len(compact) > 18 else "")

    def _build_working_title(self, idea: str) -> str:
        if not idea:
            return "未命名长篇小说"
        compact = idea.replace("\n", " ").strip()
        return f"{compact[:18]}..."


__all__ = ["InitBriefResult", "OutlineResult", "StoryConsultant", "TocResult"]
