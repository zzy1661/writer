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
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field

from writer.config import Settings
from writer.llm import get_llm
from writer.llm.structured import invoke_structured_json

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class OutlineResult:
    """A lightweight outline response for the initial CLI workflow."""

    title: str
    premise: str
    chapters: list[str]


class _OutlinePayload(BaseModel):
    title: str = Field(min_length=1)
    premise: str
    chapters: list[str] = Field(min_length=4)


class StoryConsultant:
    """Screenwriting consultant — drafts four-act outlines from a premise."""

    def __init__(
        self,
        settings: Settings,
        *,
        llm: BaseChatModel | None = None,
    ) -> None:
        self._settings = settings
        self._llm = llm

    def draft_outline(self, idea: str) -> OutlineResult:
        normalized_idea = idea.strip()
        if self._settings.has_api_key or self._llm is not None:
            try:
                return self._draft_outline_with_llm(normalized_idea)
            except Exception as exc:  # noqa: BLE001 — role must degrade gracefully
                log.warning("LLM 大纲生成失败,回退到本地四幕大纲: %r", exc, exc_info=True)
        return self._draft_outline_fallback(normalized_idea)

    def _draft_outline_fallback(self, normalized_idea: str) -> OutlineResult:
        title = self._build_working_title(normalized_idea)

        return OutlineResult(
            title=title,
            premise=normalized_idea,
            chapters=[
                "第一幕：主角处境与核心欲望",
                "第二幕：进入新世界并遭遇主要阻力",
                "第三幕：代价升级，关系与秘密浮出水面",
                "第四幕：失败后的反击与终局选择",
            ],
        )

    def _draft_outline_with_llm(self, idea: str) -> OutlineResult:
        llm = self._llm or get_llm(self._settings)
        payload = invoke_structured_json(
            llm,
            [
                SystemMessage(
                    content=(
                        "你是长篇中文网文的编剧顾问。你的任务是基于一句话创意，"
                        "生成可落地的大纲种子，而不是正文。"
                    )
                ),
                HumanMessage(
                    content=(
                        f"创意: {idea or '未命名长篇小说'}\n"
                        "请返回一个大纲 JSON: title 为书名或工作名; premise 为扩写后的核心前提; "
                        "chapters 为 4 到 8 条阶段性章节/篇章规划。每条要包含冲突、转折或悬念。"
                    )
                ),
            ],
            _OutlinePayload,
        )
        chapters = [chapter.strip() for chapter in payload.chapters if chapter.strip()]
        if len(chapters) < 4:
            msg = "LLM 大纲章节少于 4 条"
            raise ValueError(msg)
        return OutlineResult(
            title=payload.title.strip(),
            premise=payload.premise.strip(),
            chapters=chapters,
        )

    def _build_working_title(self, idea: str) -> str:
        if not idea:
            return "未命名长篇小说"
        compact = idea.replace("\n", " ").strip()
        return f"{compact[:18]}..."


__all__ = ["OutlineResult", "StoryConsultant"]
