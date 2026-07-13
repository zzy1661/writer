"""Agent 引擎状态机。

:class:`Engine` 是引擎层的主类 —— 持有 ``EngineDeps``（DI 容器）与
``EngineConfig``（per-loop 配置），并暴露 ``run(ctx)`` 作为每轮的
async generator 入口。

为什么这里有个 ``Engine`` 类（而不是一组自由函数）：

* 6 个 helper（``_run_*``）全都接收同样的 ``(action, ctx, deps, cfg)``
  参数，把这些状态抽到 ``self`` 上能消除重复参数传递。
* CLI 与 e2e 调用方只需要关心 ``engine.run(ctx)`` —— 不再关心 deps 与
  cfg 的内部接线。
* 把 ``Engine`` 视为**对象**（而非"engine 是个东西"这种抽象层名），
  让 ``EngineDeps`` / ``EngineContext`` / ``EngineConfig`` 的命名
  真正对应到实体对象上（消除 ``EngineDeps`` 命名里"Engine 对象存在吗"的歧义）。

Public API：
* ``run(ctx)`` —— 单轮入口，``AsyncIterator`` 产出 ``TextChunk`` /
  ``ActionEvent`` / ``Interrupt`` / ``ToolCall`` / ``ToolResult`` /
  ``Done`` / ``ErrorEvent``。
* ``replace_deps(new_deps)`` —— 返回新 ``Engine``（rebind 模式，
  与 ``EngineDeps.rebind_*`` 对称）。

历史：

Phase 2 接线（per ``loop.py`` 旧 docstring）：
* ``/大纲`` 的 ``run_command`` 通过 ``_run_directive`` 派发到 Markdown 范式
  的 agent 指令；LLM 消费指令 body 并使用 tool registry 写出大纲。
* ``write_chapter`` / ``review_chapter`` 通过 ``start_workflow`` 派发到
  :meth:`EngineDeps.run_workflow`。

Phase 3 接线（本类，per change ``add-llm-and-complete-engine-loop``）：
* ``call_tool`` 通过 ``self._deps.tool_registry`` 解析工具，由
  ``self._deps.tool_runtime`` 调用。
* ``ask_user`` 产出 ``Interrupt`` 让 REPL 可以提示用户，然后产出
  ``Done('ask_user')``。
* 所有异常（路由器、工具、工作流）都会被捕获，并以 ``ErrorEvent``
  后接 ``Done('aborted')`` 的形式暴露。``ErrorEvent.traceback``
  携带格式化堆栈。
* ``EngineConfig.fast_mode`` 抑制诊断用的 ``[engine]`` 日志块。
"""

from __future__ import annotations

import logging
import traceback
from collections.abc import AsyncIterator
from pathlib import Path

from writer.engine.config import EngineConfig
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


class Engine:
    """Agent 引擎状态机 —— 异步事件流生成器。

    拥有：
    - ``deps`` — :class:`writer.engine.deps.EngineDeps`（长生命周期
      DI 容器；project_root 变更时通过 ``replace_deps`` 整体替换）。
    - ``cfg`` — :class:`writer.engine.config.EngineConfig`（per-loop 配置，
      构造时初始化一次）。

    不拥有（per-turn 由调用方传入）：
    - ``ctx`` — :class:`EngineContext`（单轮不可变输入）。
    """

    def __init__(
        self,
        deps: EngineDeps,
        cfg: EngineConfig | None = None,
    ) -> None:
        self._deps = deps
        self._cfg = cfg or EngineConfig(session_id="")

    @property
    def deps(self) -> EngineDeps:
        return self._deps

    @property
    def cfg(self) -> EngineConfig:
        return self._cfg

    def replace_deps(self, new_deps: EngineDeps) -> Engine:
        """返回一个新的 ``Engine``，``deps`` 已被替换。

        与 :meth:`EngineDeps.rebind_*` 对称，用于
        :meth:`writer.session.EngineSession.set_project_root` 等
        需要整体替换依赖的场景。``cfg`` 保持不变（同一进程内的
        ``fast_mode`` 等配置不变）。
        """
        return Engine(deps=new_deps, cfg=self._cfg)

    def replace_cfg(self, new_cfg: EngineConfig) -> Engine:
        """返回一个新的 ``Engine``，``cfg`` 已被替换。"""
        return Engine(deps=self._deps, cfg=new_cfg)

    async def run(
        self,
        ctx: EngineContext,
    ) -> AsyncIterator[
        TextChunk
        | ActionEvent
        | Interrupt
        | ToolCall
        | ToolResult
        | Done
        | ErrorEvent
    ]:
        """单轮入口：派发一次，产出事件直至 ``Done``。

        ``ctx`` 由调用方构造（典型来源是
        :meth:`writer.session.EngineSession.run_turn`），作为不可变输入。
        """
        async for event in self._engine_loop(ctx):
            yield event

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _log(self, text: str) -> TextChunk:
        """诊断日志块；仅在 ``cfg.fast_mode`` 为 False 时产出。"""

        return TextChunk(text=text)

    async def _engine_loop(
        self,
        ctx: EngineContext,
    ) -> AsyncIterator[
        TextChunk
        | ActionEvent
        | Interrupt
        | ToolCall
        | ToolResult
        | Done
        | ErrorEvent
    ]:
        """每轮内部循环：派发一次，然后产出 ``Done``。

        整体 body 被 ``try/except`` 包裹，让路由器、工具或工作流中
        出现意外失败时产出 ``ErrorEvent`` 后接 ``Done(aborted)``，而不是
        从 async generator 中冒泡出去。两个 except 分支都会把堆栈
        捕获进 ``ErrorEvent.traceback``（per arch-optimizer M4），
        让 REPL 输出可以直接贴进 bug report 而无需重跑引擎。
        """

        deps = self._deps
        cfg = self._cfg

        try:
            if not cfg.fast_mode:
                yield self._log(f"[engine] 分析输入: {ctx.user_input!r}\n")

            action = deps.route(ctx.user_input, ctx.project_state)
            yield ActionEvent(action=action)

            if action.command == "/init" and action.action_type == "run_command":
                async for event in self._maybe_run_init_brief_or_block(ctx):
                    yield event
                if _init_turn_handled(
                    ctx.user_input, ctx.project_root, ctx.project_state
                ):
                    return

            # 先按 ``action.kind`` 派发（per ``fea-agent-mirror``）——
            # ``kind="agent"`` 的 action 走 agent 路径，无论底层
            # ``action_type`` 是什么（LLM 可能发出 ``answer_directly``，
            # 因为 agent 通常以散文回答）。
            if action.kind == "agent":
                async for event in self._run_agent(action, ctx):  # type: ignore[assignment]
                    yield event
                return

            match action.action_type:
                case "answer_directly":
                    yield TextChunk(text=action.answer or "")
                    yield Done(reason="answered", payload={"answer": action.answer})

                case "run_command":
                    if action.command == "/init":
                        async for event in self._run_init_command(ctx):
                            yield event
                    elif action.command and (
                        directive := deps.directive_registry.get(action.command)
                    ) is not None:
                        # 动态派发：任何映射到已注册 Directive 的斜杠命令
                        # 都走 LLM 指令执行路径。新增 directive 无需触碰本分支；
                        # DirectiveRegistry 是唯一的真理来源。
                        if not cfg.fast_mode:
                            yield self._log(
                                f"[engine] {action.command} → directive "
                                f"({directive.command})\n",
                            )
                        async for event in self._run_directive(directive, ctx):  # type: ignore[assignment]
                            yield event
                    else:
                        if not cfg.fast_mode:
                            yield self._log(
                                f"[engine] 命令 {action.command} 待执行\n"
                            )
                        yield Done(
                            reason="command_pending",
                            payload={"command": action.command},
                        )

                case "call_tool":
                    if deps.tool_loop is not None:
                        # LLM 驱动的多步工具循环（ReAct 风格）。
                        # 循环观察 ``ToolResult`` 事件并可能继续调用工具，
                        # 直到模型发出 ``answer_directly`` 或预算耗尽。
                        # 纯规则部署（无 API key）保持 ``tool_loop = None``，
                        # 走同步 ``_run_tool`` 路径 —— 通用情况零 LLM 成本。
                        async for event in self._run_tool_loop(  # type: ignore[assignment]
                            action, ctx
                        ):
                            yield event
                    else:
                        async for event in self._run_tool(action):  # type: ignore[assignment]
                            yield event

                case "start_workflow":
                    async for event in self._run_workflow(  # type: ignore[assignment]
                        action.workflow or "", ctx
                    ):
                        yield event

                case "ask_user":
                    if not cfg.fast_mode:
                        yield self._log(
                            f"[engine] 需要用户补充: {action.user_prompt}\n"
                        )
                    prompt = action.user_prompt or "请补充信息"
                    yield Interrupt(type="text", prompt=prompt, options=None)
                    yield Done(reason="ask_user", payload={"prompt": prompt})

        except ToolError as exc:
            # ``ToolError`` 是领域异常（路径 / 权限 / 未找到工具 /
            # 未找到工作流）；捕获堆栈让用户能看到失败源自工具 / 工作流的
            # 哪个位置，而无需挂调试器。
            tb = traceback.format_exc()
            log.warning("工具错误: %s", exc, exc_info=True)
            yield ErrorEvent(message=f"工具错误: {exc}", traceback=tb)
            yield Done(reason="aborted", payload={"error": str(exc)})
        except SkillError as exc:
            # ``SkillError`` 是 Skill 侧的 ``ToolError`` 对等物：由 ``Skill.run``
            # 抛出，代表可恢复的失败（缺失 project root、前置条件未满足、
            # 参数格式错误）。附带被拒绝的命令，让 REPL 能渲染出有用的红色 ✗
            # 提示，告诉用户 *哪个* skill 失败。
            tb = traceback.format_exc()
            log.warning("技能错误: %s", exc, exc_info=True)
            # SkillError 本身不携带 skill command —— 从最近派发的 action 恢复，
            # 保持 payload 稳定。
            command = getattr(exc, "command", getattr(action, "command", None))
            yield ErrorEvent(message=f"技能错误: {exc}", traceback=tb)
            yield Done(
                reason="aborted",
                payload={"error": str(exc), "command": command},
            )
        except Exception as exc:  # noqa: BLE001 — 引擎边界绝不能抛
            tb = traceback.format_exc()
            log.exception("引擎边界异常: %s", exc)
            yield ErrorEvent(message=f"引擎异常: {exc}", traceback=tb)
            yield Done(reason="aborted", payload={"error": str(exc)})

    # ------------------------------------------------------------------
    # Dispatch helpers
    # ------------------------------------------------------------------

    async def _run_tool(
        self, action: AgentAction
    ) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done]:
        """为 ``call_tool`` action 解析、调用并产出事件。"""

        deps = self._deps
        cfg = self._cfg

        name = action.tool_name or ""
        arguments = dict(action.arguments)

        if not cfg.fast_mode:
            yield TextChunk(text=f"[engine] 工具 {name} 调用中…\n")
        yield ToolCall(name=name, arguments=arguments)

        # 工具层自身的 try/except 位于 _engine_loop 之内，会捕获
        # ToolError；这里只是调用并让异常向外传播，由外层边界产生
        # ErrorEvent + Done(aborted)。
        result = deps.tool_registry.invoke(name, deps.tool_runtime, **arguments)
        yield ToolResult(name=name, output=result.output)

        if not cfg.fast_mode:
            yield TextChunk(text=f"[engine] 工具 {name} 完成\n")
        yield Done(
            reason="tool_completed",
            payload={"tool": name, "output": result.output},
        )

    async def _run_tool_loop(
        self, action: AgentAction, ctx: EngineContext
    ) -> AsyncIterator[TextChunk | ToolCall | ToolResult | Done]:
        """多步调用委托给 :class:`writer.llm.agent.ReActAgent`。

        前置条件：``self._deps.tool_loop is not None``（引擎的
        ``case "call_tool"`` 分支只在这种情况下路由到这里）。

        循环内抛出的 ``ToolError`` 向外传播，让外层 ``_engine_loop`` 的
        ``except ToolError`` 分支产出与同步 ``_run_tool`` 一致的
        ``ErrorEvent + Done(aborted)`` UX —— 此接缝不做吞异常。
        """

        deps = self._deps
        cfg = self._cfg

        if deps.tool_loop is None:
            # 防御性：考虑到引擎 ``case "call_tool"`` 守卫，理论上走不到这里，
            # 但清晰的报错能让任何后续维护者一眼看清契约。
            msg = "_run_tool_loop called without deps.tool_loop"
            raise RuntimeError(msg)
        if not cfg.fast_mode:
            yield self._log(
                f"[engine] 进入 LLM 工具循环(action={action.action_type})\n"
            )
        async for event in deps.tool_loop.run(action, ctx, deps, cfg):
            yield event

    async def _run_workflow(
        self, name: str, ctx: EngineContext
    ) -> AsyncIterator[TextChunk | Done]:
        """运行已注册的工作流并按其 :class:`WorkflowResult` 派发。

        将 ``result.status`` 映射为 ``DoneReason``：

        * ``"completed"`` → ``Done(reason="workflow_completed", payload=...)``，
          payload 中携带工作流的 ``artifacts``（路径转字符串）和
          ``metrics``，便于 CLI 渲染。
        * ``"failed"`` → ``Done(reason="aborted", payload={"workflow": name, "error": ...})``，
          让现有引擎边界的 aborted 分支以一致的方式处理错误 UX。
        * ``"pending"`` → ``Done(reason="aborted", payload={"workflow": name, "decision": "needs_rewrite"})``
          （PR3+）。PR1 中用于 ``workflow_pending`` 的弃用分支已移除；
          需要重写信号的工作流通过 ``status="pending"`` 表达，
          但引擎通过 ``aborted`` reason 暴露（附带 ``decision`` metric
          以便消费者区分"需要重写"和真实失败）。

        旧的 ``[engine] 工作流 X 启动`` 日志块在非 fast 模式下保留，
        以保持与原 stub 路径的诊断一致性。
        """

        deps = self._deps
        cfg = self._cfg

        if not cfg.fast_mode:
            yield TextChunk(text=f"[engine] 工作流 {name} 启动\n")
        result = deps.run_workflow(name, ctx)
        for chunk in result.chunks:
            yield TextChunk(text=chunk)
        if result.status == "completed":
            yield Done(
                reason="workflow_completed",
                payload={
                    "workflow": name,
                    "artifacts": {k: str(v) for k, v in result.artifacts.items()},
                    "metrics": dict(result.metrics),
                },
            )
            return
        if result.status == "pending":
            # PR3+：pending = 工作流产出了一个「需要上游动作」的信号
            # （例如 review_chapter 的 needs_rewrite）。引擎以 ``aborted``
            # 暴露，附带 ``decision`` metric 让 REPL 能展示有用的提示。
            # ``workflow_pending`` 不再是合法的 ``DoneReason``。
            decision = str(result.metrics.get("decision", "needs_rewrite"))
            yield Done(
                reason="aborted",
                payload={
                    "workflow": name,
                    "decision": decision,
                    "artifacts": {k: str(v) for k, v in result.artifacts.items()},
                    "metrics": dict(result.metrics),
                },
            )
            return
        # status == "failed"
        error_msg = str(result.metrics.get("error", "")) or f"工作流 {name} 失败"
        yield Done(
            reason="aborted",
            payload={"workflow": name, "error": error_msg},
        )

    async def _run_agent(
        self, action: AgentAction, ctx: EngineContext
    ) -> AsyncIterator[
        TextChunk | ActionEvent | Interrupt | ToolCall | ToolResult | Done | ErrorEvent
    ]:
        """将 ``kind="agent"`` action 派发给 LLM，注入 agent body。

        Per ``fea-agent-mirror`` Decision 7：引擎组装一次 LLM 调用，
        其 system prompt 由所选 agent 的 ``body``（agent 的身份 / 角色描述）
        与题材特定的大纲模板拼接。LLM 通过现有的
        :class:`writer.llm.agent.ReActAgent` 路径调用（配置了 API key 时），
        让模型在产出结构化大纲前可用 tool registry 读取项目状态。

        没有 LLM 时（``deps.tool_loop is None``）helper 产出一段预览
        TextChunk 描述被选中的 agent（不生成真实大纲 —— 之前的
        ``writer.roles.StoryAgent._draft_outline_fallback`` 已在
        ``chg-remove-roles`` 中删除）。CLI 在终结 ``Done`` payload 中
        渲染 agent 名称，让用户看到是哪个 agent 产出了回答。

        错误：

        * :class:`writer.agents.AgentRegistryError` 由
          ``agent_registry.require`` 在 ``action.target_agent`` 不是已知
          agent 时抛出 → 由引擎边界捕获，以
          ``ErrorEvent + Done(aborted, payload={"error": ..., "command": name})``
          暴露。
        * 其他 LLM / 工具失败由外层 ``_engine_loop`` 边界
          （``except Exception`` 分支）捕获。
        """

        from writer.agents import AgentRegistryError  # noqa: PLC0415

        deps = self._deps
        cfg = self._cfg

        agent_name = action.target_agent or ""
        try:
            agent = deps.agent_registry.require(agent_name)
        except AgentRegistryError as exc:
            # 把决策让给引擎边界的现有 ``except`` 分支：原计划是重抛为
            # ``ToolError`` 形态的 ``AgentRegistryError``；但由于
            # ``AgentRegistryError`` 是 ``ValueError``（不是 ``ToolError``），
            # 我们改为直接产出事件，避免边界的 catch-all 分支重复包装消息。
            from writer.engine.events import ErrorEvent

            tb_msg = str(exc)
            log.warning("Agent dispatch 错误: %s", exc, exc_info=True)
            yield ErrorEvent(message=f"Agent 错误: {exc}", traceback=tb_msg)
            yield Done(
                reason="aborted",
                payload={"error": str(exc), "command": agent_name},
            )
            return

        if not cfg.fast_mode:
            yield self._log(f"[engine] agent dispatch → {agent_name}\n")

        if deps.tool_loop is not None:
            # LLM 驱动路径：把 agent body 喂给现有工具循环，
            # 它已经知道如何用结构化输出 schema 和 tool registry 调用 LLM。
            # 借力 ``answer_directly`` 让循环只产出散文；
            # agent body 是 system identity，用户输入是 human message。
            agent_action = AgentAction(
                action_type="answer_directly",
                command=None,
                kind="agent",
                target_agent=agent_name,
                answer=(
                    f"[agent {agent_name!r} system identity]\n"
                    f"{agent.body}\n"
                    f"\n[user input]\n{ctx.user_input}"
                ),
            )
            async for event in deps.tool_loop.run(agent_action, ctx, deps, cfg):
                yield event
        else:
            # 没有可用 LLM —— 产出 agent body 作为预览，让用户看到选中
            # 的 agent 以及它的身份。这与引擎其他地方使用的纯规则
            # 回退路径一致（``_run_directive``）。
            yield TextChunk(
                text=(
                    f"[agent {agent_name!r} preview, no LLM configured]\n"
                    f"  name: {agent.name}\n"
                    f"  genre: {agent.genre}\n"
                    f"  body length: {len(agent.body)} chars\n"
                    f"  description: {agent.description}\n"
                )
            )
            yield Done(
                reason="answered",
                payload={
                    "agent": agent_name,
                    "genre": agent.genre,
                    "body_length": len(agent.body),
                    "llm_available": False,
                },
            )

    async def _run_directive(
        self, directive: SkillDirective, ctx: EngineContext
    ) -> AsyncIterator[TextChunk | Done | ToolCall | ToolResult]:
        """通过 LLM 工具循环执行 Markdown SKILL.md directive。

        directive 的 body 是给 LLM 的指令文本。本 helper 解析 body 中的
        ``@reference path/to/file.md`` 引用并暴露给 LLM，让它能读取相关
        引用资料。LLM 消化指令后，驱动现有 tool registry
        （``safe_read_file``、``safe_write_file`` 等）完成实际工作。

        实现状态（per chg-markdown-skills spec）：
        * Body + 解析后的引用通过现有 ``deps.tool_loop.run`` 路径注入
          LLM 上下文，该路径已处理 JSON 动作协议与工具派发。
        * Directive 的元数据（``command`` / ``description``）
          通过 ``TextChunk`` 输出给用户，便于透明。
        * 若 ``deps.tool_loop`` 为 ``None``（纯规则部署），
          helper 降级为只输出 TextChunk 的 stub，打印 directive body
          摘要 —— 没有 API key 时无法真正执行 LLM。
        """

        deps = self._deps
        cfg = self._cfg

        if not cfg.fast_mode:
            yield TextChunk(
                text=f"[engine] {directive.command} → directive ({directive.command})\n"
            )

        # 把 ``@reference path`` 提及解析为 (相对路径, 内容) 对。
        # 本地 import 以避免模块加载时的循环 import
        # （directive_discovery 已经从 skills.registry import）。
        from writer.skills.directive_discovery import resolve_references  # noqa: PLC0415

        resolved = resolve_references(directive.body, directive.references)

        if deps.tool_loop is not None:
            # 把 directive + 解析后的引用交给现有 LLM 工具循环。
            # 循环读取 action 的 body 和 references，然后驱动 tool registry。
            from writer.routing import AgentAction  # noqa: PLC0415

            action = AgentAction(
                action_type="answer_directly",
                command=directive.command,
                answer=directive.body,
            )
            # 把解析后的引用暂存到临时属性，便于循环读取；
            # 循环的契约由 answer 字段携带的 directive body 满足。
            # NOTE: 未来任务可能通过专用的 directive-aware 循环子类
            # 接入 ``resolved``。
            async for event in deps.tool_loop.run(action, ctx, deps, cfg):
                yield event
        else:
            # 没有可用 LLM —— 产出有用的预览，让用户看到 directive 本应做什么。
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

    # ------------------------------------------------------------------
    # /init 派发
    # ------------------------------------------------------------------

    async def _maybe_run_init_brief_or_block(
        self,
        ctx: EngineContext,
    ) -> AsyncIterator[TextChunk | Done]:
        """在已绑定 S1 项目上处理 REPL ``/init <brief>``，或引导 S0 用户。

        Note: REPL ``handle_repl_input`` 在 brief 形式（无 ``--flag``）下
        抢先消费 —— 调用 :func:`writer.cli._init_backend.apply_genre_and_brief`
        完成多选题材 + 补脚手架 + 写 brief。本函数现在主要服务于
        非 REPL 调用方（``Engine.run`` 直接驱动、SDK、e2e pipe 测试）
        以及 ``S0`` 引导提示。
        """

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

        async for event in self._run_init_brief_command(ctx, brief):
            yield event

    async def _run_init_brief_command(
        self,
        ctx: EngineContext,
        brief: str,
    ) -> AsyncIterator[TextChunk | Done]:
        """将创意梗概展开写入 ``创意/核心创意.md`` 和 ``AGENT.md``。"""

        cfg = self._cfg

        if ctx.project_root is None:
            msg = "未绑定项目，无法写入创意。"
            yield TextChunk(text=f"{msg}\n")
            yield Done(reason="aborted", payload={"command": "/init", "error": msg})
            return

        if not cfg.fast_mode:
            yield TextChunk(text="[engine] /init → apply_init_brief\n")

        # ``writer.agents.process_init_brief`` 是 ``chg-remove-roles``
        # 清理后唯一幸存的 Python-side 能力；我们通过
        # :func:`writer.project.init_brief.apply_init_brief` 调用它，
        # 让引擎边界无需了解 Settings。
        from writer.config import get_settings

        result = apply_init_brief(
            ctx.project_root, brief, settings=get_settings()
        )
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
        self,
        ctx: EngineContext,
    ) -> AsyncIterator[TextChunk | Done]:
        """从 ``/init <name>`` 创建项目 workspace 并返回其根目录。"""

        cfg = self._cfg

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


def _init_turn_handled(
    user_input: str,
    project_root: Path | None,
    project_state: str,
) -> bool:
    """当 ``/init`` 在状态矩阵校验之前已完整处理时返回 True。"""

    if should_run_init_brief(
        user_input,
        project_root=project_root,
        project_state=project_state,
    ):
        return True

    rest = extract_init_brief_text(user_input)
    return project_root is None and bool(rest) and looks_like_creative_brief(rest)


__all__ = ["Engine"]
