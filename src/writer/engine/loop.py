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

Phase 3 wiring (this module, per change
``add-llm-and-complete-engine-loop``):

* ``call_tool`` resolves the tool via ``deps.tool_registry``, invokes it
  through ``deps.tool_runtime``, and emits ``ToolCall`` / ``ToolResult``
  events around a terminal ``Done('tool_completed')``.
* ``ask_user`` emits ``Interrupt`` so the REPL can prompt the user, then
  ``Done('ask_user')`` to mark the turn complete.
* All exceptions (router, tool, workflow) are caught and surfaced as
  ``ErrorEvent`` followed by ``Done('aborted')``. ``ErrorEvent.traceback``
  carries the formatted stack trace so post-mortem debugging doesn't
  require attaching a debugger.
* ``EngineConfig.fast_mode`` suppresses diagnostic ``[engine]`` log chunks.
* 2026-07-05 (arch-optimizer M4 / Q7): engine boundary logs via stdlib
  ``logging`` and the ``/大纲`` argument extraction uses
  :meth:`str.removeprefix` (defensive against multi-space / repeated
  prefix edge cases).
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import AsyncIterator

from writer.engine.config import EngineConfig, build_engine_config
from writer.engine.context import EngineContext
from writer.engine.deps import EngineDeps
from writer.engine.events import (
    ActionEvent,
    Done,
    ErrorEvent,
    Interrupt,
    TextChunk,
    ToolCall,
    ToolResult,
)
from writer.routing import AgentAction
from writer.tools.errors import ToolError

log = logging.getLogger(__name__)


def _log(text: str, cfg: EngineConfig) -> TextChunk:
    """Diagnostic log chunk; emitted only when ``cfg.fast_mode`` is False."""

    del cfg  # currently no per-chunk logic; reserved for future log levels
    return TextChunk(text=text)


async def run_engine(
    ctx: EngineContext,
    deps: EngineDeps,
    *,
    config: EngineConfig | None = None,
) -> AsyncIterator[TextChunk | ActionEvent | Interrupt | ToolCall | ToolResult | Done | ErrorEvent]:
    """Public entry point. Wraps ``_engine_loop`` for future hooks."""

    cfg = config or build_engine_config(ctx)
    async for event in _engine_loop(ctx, deps, cfg):
        yield event


async def _engine_loop(
    ctx: EngineContext,
    deps: EngineDeps,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | ActionEvent | Interrupt | ToolCall | ToolResult | Done | ErrorEvent]:
    """Per-turn inner loop: dispatch once, then yield ``Done``.

    The whole body is wrapped in ``try/except`` so an unexpected failure
    in the router, tool, or workflow produces an ``ErrorEvent`` followed
    by ``Done(aborted)`` instead of bubbling out of the async generator.
    Both catch arms capture the traceback into ``ErrorEvent.traceback``
    (per arch-optimizer M4) so REPL output can be pasted into bug
    reports without rerunning the engine.
    """

    try:
        if not cfg.fast_mode:
            yield _log(f"[engine] 分析输入: {ctx.user_input!r}\n", cfg)

        action = deps.route(ctx.user_input, ctx.project_state)
        yield ActionEvent(action=action)

        match action.action_type:
            case "answer_directly":
                yield TextChunk(text=action.answer or "")
                yield Done(reason="answered", payload={"answer": action.answer})

            case "run_command":
                if action.command == "/大纲":
                    async for event in _run_outline_command(ctx, deps, cfg):
                        yield event
                else:
                    if not cfg.fast_mode:
                        yield _log(f"[engine] 命令 {action.command} 待执行\n", cfg)
                    yield Done(
                        reason="command_pending",
                        payload={"command": action.command},
                    )

            case "call_tool":
                async for event in _run_tool(action, deps, cfg):  # type: ignore[assignment]
                    yield event

            case "start_workflow":
                async for event in _run_workflow(action.workflow or "", ctx, deps, cfg):
                    yield event

            case "ask_user":
                if not cfg.fast_mode:
                    yield _log(
                        f"[engine] 需要用户补充: {action.user_prompt}\n", cfg
                    )
                prompt = action.user_prompt or "请补充信息"
                yield Interrupt(type="text", prompt=prompt, options=None)
                yield Done(reason="ask_user", payload={"prompt": prompt})

    except ToolError as exc:
        # ``ToolError`` is a domain exception (path / permission / tool not
        # found / workflow not found); capture the traceback so the user
        # can see *where* in the tool / workflow the failure originated
        # without needing to attach a debugger.
        tb = traceback.format_exc()
        log.warning("工具错误: %s", exc, exc_info=True)
        yield ErrorEvent(message=f"工具错误: {exc}", traceback=tb)
        yield Done(reason="aborted", payload={"error": str(exc)})
    except Exception as exc:  # noqa: BLE001 — engine boundary must never raise
        tb = traceback.format_exc()
        log.exception("引擎边界异常: %s", exc)
        yield ErrorEvent(message=f"引擎异常: {exc}", traceback=tb)
        yield Done(reason="aborted", payload={"error": str(exc)})


async def _run_outline_command(
    ctx: EngineContext,
    deps: EngineDeps,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | Done]:
    """Dispatch ``/大纲 <创意>`` to :class:`StoryConsultant` and stream the outline."""
    if not cfg.fast_mode:
        yield TextChunk(text="[engine] /大纲 → StoryConsultant.draft_outline\n")
    # ``removeprefix`` (3.9+) replaces the previous ``[len("/大纲"):]`` slice
    # (arch-optimizer M3): the slice misbehaves when ``ctx.user_input`` is
    # exactly ``"/大纲"`` (returns the whole string, no leading space) and
    # makes the multi-space / repeated-prefix edge case silently
    # mis-parse. ``removeprefix`` is the canonical, defensive form.
    idea = ctx.user_input.removeprefix("/大纲").strip()
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


async def _run_tool(
    action: AgentAction,
    deps: EngineDeps,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done | ErrorEvent]:
    """Resolve, invoke, and yield events for a ``call_tool`` action."""

    name = action.tool_name or ""
    arguments = dict(action.arguments)

    if not cfg.fast_mode:
        yield TextChunk(text=f"[engine] 工具 {name} 调用中…\n")
    yield ToolCall(name=name, arguments=arguments)

    # The tool layer's own try/except inside _engine_loop will catch
    # ToolError; here we just call and let exceptions propagate up so the
    # outer boundary produces ErrorEvent + Done(aborted).
    result = deps.tool_registry.invoke(name, deps.tool_runtime, **arguments)
    yield ToolResult(name=name, output=result.output)

    if not cfg.fast_mode:
        yield TextChunk(text=f"[engine] 工具 {name} 完成\n")
    yield Done(
        reason="tool_completed",
        payload={"tool": name, "output": result.output},
    )


async def _run_workflow(
    name: str,
    ctx: EngineContext,
    deps: EngineDeps,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | Done]:
    """Run a registered workflow stub and stream its chunks."""
    if not cfg.fast_mode:
        yield TextChunk(text=f"[engine] 工作流 {name} 启动\n")
    for chunk in deps.run_workflow(name, ctx):
        yield TextChunk(text=chunk)
    yield Done(reason="workflow_pending", payload={"workflow": name})


__all__ = ["run_engine"]
