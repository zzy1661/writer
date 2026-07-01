from dataclasses import dataclass

from writer.config import Settings


@dataclass(frozen=True)
class OutlineResult:
    """A lightweight outline response for the initial CLI workflow."""

    title: str
    premise: str
    chapters: list[str]


class NovelAgent:
    """High-level facade for novel writing capabilities.

    The initial implementation is intentionally deterministic so the CLI can be
    tested without network access. LLM and LangGraph workflows can later live
    behind this facade without changing CLI commands.
    """

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
