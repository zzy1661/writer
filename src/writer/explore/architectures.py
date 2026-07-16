"""内置写作架构目录及其 Markdown 说明。"""

from __future__ import annotations

import importlib.resources
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ArchitectureSpec:
    """一种可供 explore 模式推荐的写作架构。"""

    name: str
    short_description: str
    markdown: str


def _read_shipped_architectures() -> str:
    resource = importlib.resources.files("writer.explore._shipped").joinpath(
        "architectures.md"
    )
    return resource.read_text(encoding="utf-8")


def _first_paragraph(text: str) -> str:
    paragraphs = re.split(r"\n\s*\n", text.strip())
    for paragraph in paragraphs:
        value = " ".join(line.strip() for line in paragraph.splitlines()).strip()
        if value:
            return value
    return ""


def parse_arch_blocks(markdown: str) -> list[ArchitectureSpec]:
    """按二级标题解析 shipped Markdown 中的写作架构块。"""

    blocks = re.split(r"(?m)(?=^##\s+)", markdown)
    specs: list[ArchitectureSpec] = []
    for block in blocks:
        block = block.strip()
        if not block.startswith("## "):
            continue
        heading, _, body = block.partition("\n")
        name = heading.removeprefix("## ").strip()
        if not name:
            continue
        specs.append(
            ArchitectureSpec(
                name=name,
                short_description=_first_paragraph(body),
                markdown=block + "\n",
            )
        )
    return specs


ARCHITECTURES: list[ArchitectureSpec] = parse_arch_blocks(_read_shipped_architectures())
_ARCHITECTURES_BY_NAME = {spec.name: spec for spec in ARCHITECTURES}


def lookup_architecture(name: str) -> ArchitectureSpec:
    """返回指定写作架构；未知名称抛出 ``KeyError``。"""

    return _ARCHITECTURES_BY_NAME[name]


__all__ = [
    "ARCHITECTURES",
    "ArchitectureSpec",
    "lookup_architecture",
    "parse_arch_blocks",
]
