"""Story Consultant role — the screenwriting specialist.

This is one *role* in the agent system (per 备忘 04 / 16 / 17), alongside
others that will land later (``proofreader``, ``historian``, ``reviewer``).
A role exposes a small capability surface — currently
:meth:`StoryConsultant.draft_outline` — that the engine, CLI, and workflow
stubs call explicitly. Roles do not invoke each other directly; cross-role
composition happens at the workflow graph layer.

The MVP implementation is deterministic and intentionally network-free so
the CLI can be exercised end-to-end without an LLM. The same facade will
back the future LangChain / LangGraph-backed implementation without
changing CLI commands.
"""

from dataclasses import dataclass

from writer.config import Settings


@dataclass(frozen=True)
class OutlineResult:
    """A lightweight outline response for the initial CLI workflow."""

    title: str
    premise: str
    chapters: list[str]


class StoryConsultant:
    """Screenwriting consultant — drafts four-act outlines from a premise."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings

    def draft_outline(self, idea: str) -> OutlineResult:
        normalized_idea = idea.strip()
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

    def _build_working_title(self, idea: str) -> str:
        if not idea:
            return "未命名长篇小说"
        compact = idea.replace("\n", " ").strip()
        return f"{compact[:18]}..."


__all__ = ["OutlineResult", "StoryConsultant"]
