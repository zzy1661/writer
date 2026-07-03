"""Engine main loop.

The engine is a *stateless* ``AsyncGenerator``: callers (REPL, future
``EngineSession``) own the per-session state and re-invoke ``run_engine``
each turn. The benefits over a single ``run() -> Result`` mirror Claude
Code §一·1.2: streaming output, late-binding decisions, and clean
cancellation.

Phase 2 wiring (per 本次重构 Phase 2):

* ``run_command`` for ``/大纲`` dispatches to
  :meth:`writer.roles.StoryConsultant.draft_outline` and streams the
  outline as ``TextChunk`` events before a terminal ``Done('answered')``.
* ``start_workflow`` for ``write_chapter`` / ``review_chapter`` (and any
  future registered workflow) dispatches to
  :meth:`writer.engine.deps.EngineDeps.run_workflow` and streams the
  workflow's chunks before ``Done('workflow_pending')``.
* All other action types short-circuit to a terminal ``Done`` (MVP).
"""

from __future__ import annotations

from collections.abc import AsyncIterator

from writer.engine.config import EngineConfig, build_engine_config
from writer.engine.context import EngineContext
from writer.engine.deps import EngineDeps
from writer.engine.events import ActionEvent, Done, TextChunk


async def run_engine(
    ctx: EngineContext,
    deps: EngineDeps,
    *,
    config: EngineConfig | None = None,
) -> AsyncIterator[TextChunk | ActionEvent | Done]:
    """Public entry point. Wraps ``_engine_loop`` for future hooks."""

    cfg = config or build_engine_config(ctx)
    async for event in _engine_loop(ctx, deps, cfg):
        yield event


async def _engine_loop(
    ctx: EngineContext,
    deps: EngineDeps,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | ActionEvent | Done]:
    """Per-turn inner loop: dispatch once, then yield ``Done``."""

    yield TextChunk(text=f"[engine] 分析输入: {ctx.user_input!r}\n")
    action = deps.route(ctx.user_input, ctx.project_state)
    yield ActionEvent(action=action)

    match action.action_type:
        case "answer_directly":
            yield TextChunk(text=action.answer or "")
            yield Done(reason="answered", payload={"answer": action.answer})

        case "run_command":
            if action.command == "/大纲":
                async for event in _run_outline_command(ctx, deps):
                    yield event
            else:
                yield TextChunk(text=f"[engine] 命令 {action.command} 待执行")
                yield Done(
                    reason="command_pending",
                    payload={"command": action.command},
                )

        case "call_tool":
            yield TextChunk(text=f"[engine] 工具 {action.tool_name} 待调用")
            yield Done(
                reason="tool_pending",
                payload={"tool": action.tool_name},
            )

        case "start_workflow":
            async for event in _run_workflow(action.workflow or "", ctx, deps):
                yield event

        case "ask_user":
            yield TextChunk(text=f"[engine] 需要用户补充: {action.user_prompt}")
            yield Done(
                reason="ask_user",
                payload={"prompt": action.user_prompt},
            )


async def _run_outline_command(
    ctx: EngineContext,
    deps: EngineDeps,
) -> AsyncIterator[TextChunk | Done]:
    """Dispatch ``/大纲 <创意>`` to :class:`StoryConsultant` and stream the outline."""
    yield TextChunk(text="[engine] /大纲 → StoryConsultant.draft_outline\n")
    idea = ctx.user_input[len("/大纲"):].strip()
    outline = deps.story_consultant.draft_outline(idea)

    yield TextChunk(text=f"标题: {outline.title}\n")
    yield TextChunk(text=f"前提: {outline.premise}\n")
    for chapter in outline.chapters:
        yield TextChunk(text=f"- {chapter}\n")

    yield Done(
        reason="answered",
        payload={
            "answer": outline.title,
            "outline": True,
            "chapter_count": len(outline.chapters),
        },
    )


async def _run_workflow(
    name: str,
    ctx: EngineContext,
    deps: EngineDeps,
) -> AsyncIterator[TextChunk | Done]:
    """Run a registered workflow stub and stream its chunks."""
    yield TextChunk(text=f"[engine] 工作流 {name} 启动\n")
    for chunk in deps.run_workflow(name, ctx):
        yield TextChunk(text=chunk)
    yield Done(reason="workflow_pending", payload={"workflow": name})


__all__ = ["run_engine"]
