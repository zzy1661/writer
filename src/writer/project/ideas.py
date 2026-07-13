"""从项目的 ``创意/`` 目录加载创作素材。"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

# 从集中式 prompts 模块 re-export 大纲 system prompt，
# 让之前用 ``from writer.project.ideas import OUTLINE_SYSTEM_PROMPT``
# 的调用方可以保持工作而无需修改。本地文件专注于项目层关注点
# （文件系统布局、IdeasContext 组装）。
from writer.prompts.agents import OUTLINE_TEMPLATE_STORY

CORE_IDEA_FILENAME = "核心创意.md"
_SKIP_FILENAMES = frozenset({CORE_IDEA_FILENAME, "README.md", "简介.md"})
_TEXT_SUFFIXES = frozenset({".md", ".txt"})


@dataclass(frozen=True)
class IdeasContext:
    """从 ``创意/`` 为大纲生成组装的创作上下文。"""

    core_idea: str | None = None
    supplementary_docs: tuple[tuple[str, str], ...] = ()

    @property
    def has_content(self) -> bool:
        return bool(self.core_idea) or bool(self.supplementary_docs)


def load_ideas_context(project_root: Path | None) -> IdeasContext:
    """读取 ``创意/`` 下的 ``核心创意.md`` 与其他文本文件。"""

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
    """为大纲 LLM 调用构造 HumanMessage body。"""

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
