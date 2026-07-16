"""explore 模式的身份与结构化对话 prompt。"""

from __future__ import annotations

import importlib.resources
import re

from langchain_core.prompts import ChatPromptTemplate


def _read_explore_identity() -> str:
    resource = importlib.resources.files("writer.explore._shipped").joinpath("编剧.md")
    text = resource.read_text(encoding="utf-8")
    match = re.match(r"\A---\s*\n.*?\n---\s*\n(?P<body>.*)\Z", text, re.DOTALL)
    if match is None:
        return text.strip()
    return match.group("body").strip()


EXPLORE_IDENTITY = _read_explore_identity()

EXPLORE_SYSTEM_TEMPLATE: ChatPromptTemplate = ChatPromptTemplate.from_messages(
    [
        (
            "system",
            EXPLORE_IDENTITY
            + "\n\n任务:用户正在为小说确定核心设定，你需要:\n"
            "1. 在至多 5 轮内，通过自由提问与用户共同完善故事核；\n"
            "2. 引导用户明确题材分类（其他、历史、言情、玄幻、科幻、悬疑）；\n"
            "3. 推荐 1 个最契合本故事的写作架构（从下列 8 种方法中选择）；\n"
            "4. 收尾时输出完整 ExploreOutcome 字段（core_idea / requirements / genres / architecture）。\n\n"
            "可用写作架构列表（节选）:\n"
            "<ARCHITECTURES_MARKDOWN>\n"
            "{architectures_markdown}",
        ),
        ("human", "{brief}"),
    ]
)

__all__ = ["EXPLORE_IDENTITY", "EXPLORE_SYSTEM_TEMPLATE"]
