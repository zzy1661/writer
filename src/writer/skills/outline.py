"""Outline skill — handles ``/大纲``."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from typing import TYPE_CHECKING

from writer.project import ProjectState, refresh_agent_file
from writer.roles import OutlineResult

if TYPE_CHECKING:
    from writer.engine.config import EngineConfig
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps
    from writer.engine.events import Done, TextChunk


class OutlineSkill:
    command = "/大纲"
    description = "生成或查看大纲"
    # Matches the historical COMMAND_ALLOWED entry; see state matrix note
    # in validate_command_available. The state matrix for /大纲 stays
    # INITIALIZED + HAS_OUTLINE so the original behaviour is preserved
    # (running /大纲 in S3+ would otherwise let it clobber the existing
    # TOC pipeline state).
    requires_states = frozenset({ProjectState.INITIALIZED, ProjectState.HAS_OUTLINE})

    async def run(
        self,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        # Lazy import: see comment in ContinueWritingSkill.run().
        from writer.engine.events import Done, TextChunk

        if not cfg.fast_mode:
            yield TextChunk(text="[engine] /大纲 → outline skill\n")
        idea = ctx.user_input.removeprefix("/大纲").strip()
        outline = deps.story_consultant.draft_outline(
            idea,
            project_root=ctx.project_root,
        )
        if outline.source != "llm" and not cfg.fast_mode:
            yield TextChunk(
                text=(
                    "[提示] 本次 /大纲 使用本地四幕模板（未调用 LLM）。"
                    "请在项目目录放置 .env 或 .writer/config（含 WRITER_API_KEY），"
                    "或在启动前 export WRITER_API_KEY。\n"
                )
            )
        outline_path = _write_outline(ctx.project_root, outline)

        yield TextChunk(text=f"标题: {outline.title}\n")
        yield TextChunk(text=f"前提: {outline.premise}\n")
        for chapter in outline.chapters:
            yield TextChunk(text=f"- {chapter}\n")
        root = ctx.project_root or outline_path.parent.parent
        yield TextChunk(text=f"已写入: {outline_path.relative_to(root).as_posix()}\n")

        yield Done(
            reason="answered",
            payload={
                "answer": outline.title,
                "outline": True,
                "chapter_count": len(outline.chapters),
                "outline_path": str(outline_path),
                "outline_source": outline.source,
                "project_state": ProjectState.HAS_OUTLINE.value,
            },
        )


def _write_outline(project_root: Path | None, outline: OutlineResult) -> Path:
    if project_root is None:
        msg = "未绑定项目，无法写入大纲。请先执行 /init <项目名> 或 writer init。"
        raise ValueError(msg)

    root = project_root.resolve()
    outline_dir = root / "outline"
    outline_dir.mkdir(parents=True, exist_ok=True)
    target = outline_dir / "大纲.md"
    target.write_text(_format_outline(outline), encoding="utf-8")
    refresh_agent_file(root)
    return target


def _format_outline(outline: OutlineResult) -> str:
    chapters = "\n".join(f"- {chapter}" for chapter in outline.chapters)
    return (
        f"# {outline.title}\n\n"
        "## 前提\n\n"
        f"{outline.premise}\n\n"
        "## 四幕大纲\n\n"
        f"{chapters}\n"
    )


__all__ = ["OutlineSkill"]
