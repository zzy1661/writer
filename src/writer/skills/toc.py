"""Table-of-contents skill — handles ``/目录``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from writer.engine.config import EngineConfig
from writer.engine.context import EngineContext
from writer.engine.events import Done, TextChunk
from writer.project import ProjectState, find_outline_path, refresh_agent_file
from writer.roles import TocResult

if TYPE_CHECKING:
    from writer.engine.deps import EngineDeps


class TocSkill:
    command = "/目录"

    async def run(
        self,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        if not cfg.fast_mode:
            yield TextChunk(text="[engine] /目录 → toc skill\n")

        if ctx.project_root is None:
            msg = "未绑定项目，无法生成目录。请先执行 /init <项目名>。"
            raise ValueError(msg)

        root = ctx.project_root.resolve()
        outline_path = find_outline_path(root)
        if outline_path is None:
            msg = "未找到大纲文件。请先执行 /大纲 <创意> 生成大纲。"
            raise ValueError(msg)

        outline_text = outline_path.read_text(encoding="utf-8")
        toc = deps.story_consultant.draft_toc(outline_text)
        toc_path = _write_toc(root, toc)

        yield TextChunk(text=f"书名: {toc.title}\n")
        for chapter in toc.chapters:
            yield TextChunk(text=f"- {chapter}\n")
        yield TextChunk(text=f"已写入: {toc_path.relative_to(root).as_posix()}\n")

        yield Done(
            reason="answered",
            payload={
                "answer": toc.title,
                "toc": True,
                "chapter_count": len(toc.chapters),
                "toc_path": str(toc_path),
                "project_state": ProjectState.HAS_TOC.value,
            },
        )


def _write_toc(project_root: Path, toc: TocResult) -> Path:
    root = project_root.resolve()
    outline_dir = root / "outline"
    outline_dir.mkdir(parents=True, exist_ok=True)
    target = outline_dir / "toc.md"
    target.write_text(_format_toc(toc), encoding="utf-8")
    refresh_agent_file(root)
    return target


def _format_toc(toc: TocResult) -> str:
    chapters = "\n".join(f"- {chapter}" for chapter in toc.chapters)
    return (
        f"# {toc.title}\n\n"
        "## 章节目录\n\n"
        f"{chapters}\n"
    )


__all__ = ["TocSkill"]
