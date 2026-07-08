"""Load creative materials from a project's ``创意/`` directory."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# Re-export the outline system prompt from the centralised prompts
# module so callers that previously did
# ``from writer.project.ideas import OUTLINE_SYSTEM_PROMPT`` keep
# working without modification. The local file stays focused on
# project-layer concerns (filesystem layout, IdeasContext assembly).
from writer.prompts.consultants import OUTLINE_TEMPLATE_STORY

CORE_IDEA_FILENAME = "核心创意.md"
_SKIP_FILENAMES = frozenset({CORE_IDEA_FILENAME, "README.md"})
_TEXT_SUFFIXES = frozenset({".md", ".txt"})


@dataclass(frozen=True)
class IdeasContext:
    """Creative context assembled from ``创意/`` for outline generation."""

    core_idea: str | None = None
    supplementary_docs: tuple[tuple[str, str], ...] = ()

    @property
    def has_content(self) -> bool:
        return bool(self.core_idea) or bool(self.supplementary_docs)


def load_ideas_context(project_root: Path | None) -> IdeasContext:
    """Read ``核心创意.md`` and other text docs under ``创意/``."""

    if project_root is None:
        return IdeasContext()

    ideas_dir = project_root / "创意"
    if not ideas_dir.is_dir():
        return IdeasContext()

    core_path = ideas_dir / CORE_IDEA_FILENAME
    core_idea: str | None = None
    if core_path.is_file():
        text = core_path.read_text(encoding="utf-8").strip()
        if text:
            core_idea = text

    supplementary: list[tuple[str, str]] = []
    for path in sorted(ideas_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name in _SKIP_FILENAMES:
            continue
        if path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        text = path.read_text(encoding="utf-8").strip()
        if text:
            supplementary.append((path.name, text))

    return IdeasContext(core_idea=core_idea, supplementary_docs=tuple(supplementary))


def build_outline_user_message(*, user_instruction: str, ideas: IdeasContext) -> str:
    """Build the HumanMessage body for outline LLM calls."""

    sections: list[str] = []

    if ideas.core_idea:
        sections.append(
            "## 核心创意（大纲须以此为中心展开）\n"
            f"{ideas.core_idea}\n"
        )

    if ideas.supplementary_docs:
        sections.append("## 辅助创意素材")
        for name, content in ideas.supplementary_docs:
            sections.append(f"### {name}\n{content}\n")

    instruction = user_instruction.strip()
    if instruction:
        sections.append(f"## 本次补充指令\n{instruction}\n")
    elif not ideas.has_content:
        sections.append("创意: 未命名长篇小说\n")

    sections.append(
        "请返回一个大纲 JSON: title 为书名或工作名; premise 为扩写后的核心前提; "
        "chapters 为 4 到 8 条阶段性章节/篇章规划。每条要包含冲突、转折或悬念。"
    )
    if ideas.core_idea:
        sections.append(
            "大纲必须与「核心创意」的主轴、冲突与世界观一致；"
            "辅助素材与本次补充指令仅作补充，不得偏离核心创意。"
        )

    return "\n".join(sections)


OUTLINE_SYSTEM_PROMPT = OUTLINE_TEMPLATE_STORY


__all__ = [
    "CORE_IDEA_FILENAME",
    "IdeasContext",
    "OUTLINE_SYSTEM_PROMPT",
    "build_outline_user_message",
    "load_ideas_context",
]
