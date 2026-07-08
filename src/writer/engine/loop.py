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
from pathlib import Path

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
from writer.project import (
    ProjectState,
    create_workspace,
    detect_state,
    validate_command_available,
)
from writer.project.init_brief import (
    apply_init_brief,
    extract_init_brief_text,
    looks_like_creative_brief,
    should_run_init_brief,
)
from writer.routing import AgentAction
from writer.skills import SkillDirective
from writer.skills.errors import SkillError
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

        if action.command == "/init" and action.action_type == "run_command":
            async for event in _maybe_run_init_brief_or_block(ctx, deps, cfg):
                yield event
            if _init_turn_handled(ctx.user_input, ctx.project_root, ctx.project_state):
                return

        check = validate_command_available(
            action.command,
            ctx.project_root,
            ctx.project_state,
            skill_registry=deps.directive_registry,
        )
        if not check.ok:
            yield TextChunk(text=f"{check.reason}\n")
            yield Done(
                reason="aborted",
                payload={
                    "command": action.command,
                    "project_state": check.state.value,
                    "error": check.reason,
                },
            )
            return

        match action.action_type:
            case "answer_directly":
                yield TextChunk(text=action.answer or "")
                yield Done(reason="answered", payload={"answer": action.answer})

            case "run_command":
                if action.command == "/init":
                    async for event in _run_init_command(ctx, cfg):
                        yield event
                elif action.command and (
                    directive := deps.directive_registry.get(action.command)
                ) is not None:
                    # Dynamic dispatch: any slash command that maps to a
                    # registered Directive gets routed through the LLM
                    # directive execution path. Adding a new directive
                    # does NOT touch this branch; the DirectiveRegistry
                    # is the single source of truth.
                    if not cfg.fast_mode:
                        yield _log(
                            f"[engine] {action.command} → directive "
                            f"({directive.command})\n",
                            cfg,
                        )
                    async for event in _run_directive(directive, ctx, deps, cfg):  # type: ignore[assignment]
                        yield event
                else:
                    if not cfg.fast_mode:
                        yield _log(f"[engine] 命令 {action.command} 待执行\n", cfg)
                    yield Done(
                        reason="command_pending",
                        payload={"command": action.command},
                    )

            case "call_tool":
                if deps.tool_loop is not None:
                    # LLM-driven multi-step tool loop (ReAct-style).
                    # The loop observes ``ToolResult`` events and may
                    # continue calling tools until the model emits
                    # ``answer_directly`` or the budget runs out. Rule-only
                    # deployments (no API key) keep ``tool_loop = None``
                    # and fall through to the synchronous ``_run_tool``
                    # path — zero LLM cost for the common case.
                    async for event in _run_tool_loop(  # type: ignore[assignment]
                        action, ctx, deps, cfg
                    ):
                        yield event
                else:
                    async for event in _run_tool(action, deps, cfg):  # type: ignore[assignment]
                        yield event

            case "start_workflow":
                async for event in _run_workflow(action.workflow or "", ctx, deps, cfg):  # type: ignore[assignment]
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
    except SkillError as exc:
        # ``SkillError`` is the Skill-side equivalent of ``ToolError``:
        # raised by ``Skill.run`` for recoverable failures (missing
        # project root, unsatisfied preconditions, malformed arguments).
        # Tagged with the rejected command so the REPL can render a
        # useful red ✗ message that tells the user *which* skill
        # failed.
        tb = traceback.format_exc()
        log.warning("技能错误: %s", exc, exc_info=True)
        # The skill command isn't on the SkillError itself — recover it
        # from the last routed action to keep the payload stable.
        command = getattr(exc, "command", action.command if action else None)
        yield ErrorEvent(message=f"技能错误: {exc}", traceback=tb)
        yield Done(
            reason="aborted",
            payload={"error": str(exc), "command": command},
        )
    except Exception as exc:  # noqa: BLE001 — engine boundary must never raise
        tb = traceback.format_exc()
        log.exception("引擎边界异常: %s", exc)
        yield ErrorEvent(message=f"引擎异常: {exc}", traceback=tb)
        yield Done(reason="aborted", payload={"error": str(exc)})


def _init_turn_handled(
    user_input: str,
    project_root: Path | None,
    project_state: str,
) -> bool:
    """Return True when ``/init`` was fully handled before state-matrix checks."""

    if should_run_init_brief(
        user_input,
        project_root=project_root,
        project_state=project_state,
    ):
        return True

    rest = extract_init_brief_text(user_input)
    return project_root is None and bool(rest) and looks_like_creative_brief(rest)


async def _maybe_run_init_brief_or_block(
    ctx: EngineContext,
    deps: EngineDeps,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | Done]:
    """Handle REPL ``/init <brief>`` on a bound S1 project, or steer S0 users."""

    if not should_run_init_brief(
        ctx.user_input,
        project_root=ctx.project_root,
        project_state=ctx.project_state,
    ):
        rest = extract_init_brief_text(ctx.user_input)
        if ctx.project_root is None and rest and looks_like_creative_brief(rest):
            msg = (
                "看起来你在描述故事创意。请先执行 /init <项目名> 创建并绑定项目，"
                "再输入 /init <故事梗概> 填写创意。"
            )
            yield TextChunk(text=f"{msg}\n")
            yield Done(
                reason="aborted",
                payload={"command": "/init", "error": msg},
            )
        return

    brief = extract_init_brief_text(ctx.user_input)
    if not brief:
        msg = "用法：/init <故事梗概>，或 /init --brief <故事梗概>"
        yield TextChunk(text=f"{msg}\n")
        yield Done(reason="aborted", payload={"command": "/init", "error": msg})
        return

    if ctx.project_root is None:
        msg = "请先执行 /init <项目名> 创建并绑定项目，再输入故事创意。"
        yield TextChunk(text=f"{msg}\n")
        yield Done(reason="aborted", payload={"command": "/init", "error": msg})
        return

    state = detect_state(ctx.project_root)
    if state != ProjectState.INITIALIZED:
        description = state.value
        msg = (
            f"/init 创意访谈仅在 S1（初始化）可用；当前为 {description}。"
            "可直接编辑 创意/核心创意.md。"
        )
        yield TextChunk(text=f"{msg}\n")
        yield Done(
            reason="aborted",
            payload={
                "command": "/init",
                "project_state": state.value,
                "error": msg,
            },
        )
        return

    async for event in _run_init_brief_command(ctx, deps, cfg, brief):
        yield event


async def _run_init_brief_command(
    ctx: EngineContext,
    deps: EngineDeps,
    cfg: EngineConfig,
    brief: str,
) -> AsyncIterator[TextChunk | Done]:
    """Expand a creative brief into ``创意/核心创意.md`` and ``AGENT.md``."""

    if ctx.project_root is None:
        msg = "未绑定项目，无法写入创意。"
        yield TextChunk(text=f"{msg}\n")
        yield Done(reason="aborted", payload={"command": "/init", "error": msg})
        return

    if not cfg.fast_mode:
        yield TextChunk(text="[engine] /init → apply_init_brief\n")

    result = apply_init_brief(ctx.project_root, brief, deps.story_consultant)
    yield TextChunk(
        text=f"已写入 创意/核心创意.md（来源: {result.source}）\n"
        "已更新 AGENT.md 基本要求\n"
    )
    yield Done(
        reason="answered",
        payload={
            "command": "/init",
            "init_brief": True,
            "source": result.source,
            "project_state": ProjectState.INITIALIZED.value,
        },
    )


async def _run_init_command(
    ctx: EngineContext,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | Done]:
    """Create a project workspace from ``/init <name>`` and return its root."""

    if not cfg.fast_mode:
        yield TextChunk(text="[engine] /init → create_workspace\n")

    name = ctx.user_input.removeprefix("/init").strip()
    if not name:
        msg = "用法：/init <项目名>。例如：/init 我的小说"
        yield TextChunk(text=f"{msg}\n")
        yield Done(reason="aborted", payload={"command": "/init", "error": msg})
        return

    workspace = create_workspace(name, Path("."))
    yield TextChunk(text=f"已初始化项目: {workspace.root}\n")
    yield Done(
        reason="answered",
        payload={
            "command": "/init",
            "project_root": str(workspace.root.resolve()),
            "project_state": ProjectState.INITIALIZED.value,
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


async def _run_tool_loop(
    action: AgentAction,
    ctx: EngineContext,
    deps: EngineDeps,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done]:
    """Delegate to :class:`writer.llm.agent.LLMToolLoop` for multi-step calls.

    Pre-condition: ``deps.tool_loop is not None`` (the engine's
    ``case "call_tool"`` branch only routes here when that's true).

    ``ToolError`` raised by the loop propagates upward so the outer
    ``_engine_loop`` ``except ToolError`` arm produces the same
    ``ErrorEvent + Done(aborted)`` UX as the synchronous ``_run_tool``
    path — no exception-swallowing at this seam.
    """

    if deps.tool_loop is None:
        # Defensive: should never reach here given the engine's
        # ``case "call_tool"`` guard, but a clearly-worded error keeps
        # the contract obvious to anyone touching this later.
        msg = "_run_tool_loop called without deps.tool_loop"
        raise RuntimeError(msg)
    if not cfg.fast_mode:
        yield _log(
            f"[engine] 进入 LLM 工具循环(action={action.action_type})\n", cfg
        )
    async for event in deps.tool_loop.run(action, ctx, deps, cfg):
        yield event


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


async def _run_directive(
    directive: SkillDirective,
    ctx: EngineContext,
    deps: EngineDeps,
    cfg: EngineConfig,
) -> AsyncIterator[TextChunk | Done | ToolCall | ToolResult]:
    """Execute a Markdown SKILL.md directive via LLM tool loop.

    The directive's body is intended as instruction text for the LLM.
    This helper resolves ``@reference path/to/file.md`` mentions in
    the body and exposes them so the LLM can read the relevant
    references. Once the LLM has consumed the instructions, it drives
    the existing tool registry (``safe_read_file``,
    ``safe_write_file``, etc.) to do the actual work.

    Implementation status (per chg-markdown-skills spec):
    * Body + resolved references are injected into the LLM context
      via the existing ``deps.tool_loop.run`` path, which already
      handles the JSON-action protocol and tool dispatch.
    * The directive's metadata (``command`` / ``description`` /
      ``requires_states``) is logged to the user via ``TextChunk``
      for transparency.
    * If ``deps.tool_loop`` is ``None`` (rule-only deployment), the
      helper degrades to a TextChunk-only stub that prints the
      directive body summary — the actual LLM execution is not
      possible without an API key.
    """

    if not cfg.fast_mode:
        yield TextChunk(
            text=f"[engine] {directive.command} → directive ({directive.command})\n"
        )

    # Resolve ``@reference path`` mentions to (relpath, content) pairs.
    # Local import to avoid a circular import at module load time
    # (directive_discovery already imports from skills.registry).
    from writer.skills.directive_discovery import resolve_references  # noqa: PLC0415

    resolved = resolve_references(directive.body, directive.references)

    if deps.tool_loop is not None:
        # Hand the directive + resolved references to the existing
        # LLM tool loop. The loop reads the action's body and
        # references, then drives the tool registry.
        from writer.routing import AgentAction  # noqa: PLC0415

        action = AgentAction(
            action_type="answer_directly",
            command=directive.command,
            answer=directive.body,
        )
        # Stash resolved references on a transient attribute so the
        # loop can read them; the loop's contract is satisfied by
        # the answer field carrying the directive body.
        # NOTE: a future task may wire ``resolved`` through a
        # dedicated directive-aware loop subclass.
        async for event in deps.tool_loop.run(action, ctx, deps, cfg):
            yield event
    else:
        # No LLM available — emit a helpful preview so the user can
        # see what the directive would have done.
        yield TextChunk(
            text=(
                f"[engine] directive body (preview, no LLM configured):\n"
                f"  command: {directive.command}\n"
                f"  description: {directive.description}\n"
                f"  body length: {len(directive.body)} chars\n"
                f"  references: {len(resolved)} files\n"
                f"  scripts: {len(directive.scripts)} files\n"
            )
        )
        if resolved:
            preview = "\n".join(
                f"  ref: {relpath} ({len(content)} chars)"
                for relpath, content in resolved
            )
            yield TextChunk(text=preview + "\n")
        yield Done(
            reason="answered",
            payload={
                "directive": directive.command,
                "body_length": len(directive.body),
                "references": [relpath for relpath, _ in resolved],
                "scripts": list(directive.scripts),
                "llm_available": False,
            },
        )


__all__ = ["run_engine"]
