"""Unit tests for the agent engine MVP."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from writer.engine import (
    ActionEvent,
    Done,
    EngineContext,
    TextChunk,
    production_deps,
    run_engine,
)
from writer.engine.deps import EngineDeps
from writer.project import create_workspace, detect_state
from writer.routing import (
    AgentAction,
    IntentRouter,
    RuleBasedIntentRouter,
)

# ---------------------------------------------------------------------------
# Router classification
# ---------------------------------------------------------------------------


def test_router_classifies_write_command() -> None:
    action = RuleBasedIntentRouter().route("/创作 1.3", "S0")

    assert action.action_type == "start_workflow"
    assert action.workflow == "write_chapter"
    assert action.role == "story_agent"
    assert action.command == "/创作"


def test_router_classifies_review_command() -> None:
    action = RuleBasedIntentRouter().route("/审核 第3章", "S2")

    assert action.action_type == "start_workflow"
    assert action.workflow == "review_chapter"
    assert action.role == "reviewer"
    assert action.command == "/审核"


def test_router_classifies_tool_query() -> None:
    action = RuleBasedIntentRouter().route("查一下 F003 伏笔出现位置", "S2")

    assert action.action_type == "call_tool"
    assert action.tool_name == "foreshadow_search"
    assert action.role == "story_agent"
    # Rule extracts the F\d+ id and passes the original text as keyword
    # (sub-string fallback) so descriptive language still narrows results.
    assert action.arguments == {
        "id": "F003",
        "keyword": "查一下 F003 伏笔出现位置",
    }


def test_router_foreshadow_query_without_id_uses_keyword_only() -> None:
    action = RuleBasedIntentRouter().route("列出所有伏笔", "S2")

    assert action.action_type == "call_tool"
    assert action.tool_name == "foreshadow_search"
    assert action.arguments == {"keyword": "列出所有伏笔"}


def test_router_classifies_wordcount_command() -> None:
    action = RuleBasedIntentRouter().route("/字数统计 manuscript", "S2")

    assert action.action_type == "call_tool"
    assert action.command == "/字数统计"
    assert action.tool_name == "wordcount"
    assert action.arguments == {"path": "manuscript"}


def test_router_classifies_init_command() -> None:
    action = RuleBasedIntentRouter().route("/init", "S0")

    assert action.action_type == "run_command"
    assert action.command == "/init"


def test_router_falls_back_to_answer() -> None:
    action = RuleBasedIntentRouter().route("帮我润色下这段", "S2")

    assert action.action_type == "answer_directly"
    assert action.answer is not None
    assert "帮我润色下这段" in action.answer


def test_rule_based_router_satisfies_protocol() -> None:
    """Concrete implementation must satisfy :class:`IntentRouter` (runtime-checkable)."""

    router: IntentRouter = RuleBasedIntentRouter()
    assert isinstance(router, IntentRouter)


# ---------------------------------------------------------------------------
# Engine loop terminal events
# ---------------------------------------------------------------------------


def _consume(events: AsyncIterator[object]) -> list[object]:
    """Drain an async generator synchronously for tests."""

    import asyncio

    async def drain() -> list[object]:
        return [event async for event in events]

    return asyncio.run(drain())


def _ctx(
    text: str,
    *,
    project_root: Path | None = None,
    project_state: str = "S0",
) -> EngineContext:
    return EngineContext(
        user_input=text,
        project_root=project_root,
        project_state=project_state,
        session_id="test-session",
    )


def _workspace_ctx(text: str, root: Path) -> EngineContext:
    return _ctx(
        text,
        project_root=root,
        project_state=detect_state(root).value,
    )


def _deps_with_real_prose() -> EngineDeps:
    """构造带真实 LLM 假端的 ``EngineDeps``（用于测试 ``write_chapter``）。

    自 2026-07-14 起,``plan_chapter`` 节点严格 LLM 驱动。本 helper 让
    不配置真实 API key 的 CI 也能跑通整个 5 节点图 —— 把
    ``RealProseClient`` 与 ``review_llm`` 同时指向同一个
    :class:`_RecordingChatModel`,后者按消息内容返回 plan / draft /
    review verdict。
    """
    from langchain_core.language_models import BaseChatModel
    from langchain_core.messages import AIMessage
    from langchain_core.outputs import ChatGeneration, ChatResult

    from writer.llm.prose import RealProseClient

    class _RecordingChatModel(BaseChatModel):
        call_count: int = 0

        class Config:
            arbitrary_types_allowed = True

        @property
        def _llm_type(self) -> str:
            return "recording-fake"

        def _generate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            self.call_count += 1
            # ``invoke_structured_json`` 在 messages 前置一个
            # ``_json_contract_message`` 系统消息,所以「审核节点」不一定
            # 在 ``messages[0]``。扫描所有消息体。
            joined = "\n".join(m.content or "" for m in messages)
            if "审核节点" in joined:
                content = '{"pass": true, "score": 8, "concerns": []}'
            else:
                content = "stub real draft content for write_chapter engine test"
            return ChatResult(
                generations=[ChatGeneration(message=AIMessage(content=content))]
            )

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):  # type: ignore[override]
            return self._generate(messages, stop=stop, run_manager=run_manager, **kwargs)

    deps = production_deps()
    llm = _RecordingChatModel()
    deps.prose_client = RealProseClient(llm=llm)
    deps.review_llm = llm
    return deps


def test_engine_yields_done_for_answer() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("帮我润色下这段"), deps))

    assert any(isinstance(e, TextChunk) and "[engine] 分析输入" in e.text for e in events)
    # 自然语言输入只要被 engine 接住就行 — LLM router 可能路由到
    # answer_directly / start_workflow / call_tool 任一种，断言只锁住
    # 「ActionEvent + Done 都已发出」(Done reason 不锁)
    assert any(isinstance(e, ActionEvent) for e in events)
    assert any(isinstance(e, Done) for e in events)


def test_engine_yields_done_for_workflow(tmp_path: Path) -> None:
    deps = _deps_with_real_prose()
    workspace = create_workspace("workflow-test", tmp_path)
    (workspace.root / "大纲" / "章节目录.md").write_text("第一章", encoding="utf-8")

    events = _consume(run_engine(_workspace_ctx("/创作 1.3", workspace.root), deps))

    assert any(isinstance(e, ActionEvent) and e.action.workflow == "write_chapter" for e in events)
    # PR1: write_chapter now returns ``WorkflowResult(status="completed")``
    # so the engine emits ``Done(reason="workflow_completed")`` instead
    # of the legacy ``workflow_pending``.
    assert any(isinstance(e, Done) and e.reason == "workflow_completed" for e in events)


def test_engine_yields_done_for_tool() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("查一下 F003"), deps))

    from writer.engine import ErrorEvent, ToolCall, ToolResult

    # LLM router 可能把伏笔查询路由到 foreshadow_search / lookup_foreshadowing /
    # 其它等价的工具名；锁定具体名字会让测试脆弱。改为断言:
    # 1) 至少发出一个 ActionEvent(router 接住了意图)
    # 2) 至少发出一个 ToolCall 或 ErrorEvent(实际尝试调工具，失败也算)
    # 3) 最终以 Done 收尾
    assert any(isinstance(e, ActionEvent) for e in events)
    assert any(isinstance(e, (ToolCall, ErrorEvent)) for e in events)
    assert any(isinstance(e, Done) for e in events)
    # 防止 ToolResult 在没 ToolCall 的情况下出现(健康检查)
    assert not any(isinstance(e, ToolResult) for e in events) or any(
        isinstance(e, ToolCall) for e in events
    )


def test_engine_yields_done_for_command() -> None:
    deps = production_deps()

    events = _consume(run_engine(_ctx("/未知命令"), deps))

    assert any(isinstance(e, ActionEvent) and e.action.command == "/未知命令" for e in events)
    assert any(isinstance(e, Done) and e.reason == "command_pending" for e in events)


def test_production_deps_has_router() -> None:
    deps = production_deps()

    assert isinstance(deps, EngineDeps)
    # When the local .env has no API key, router is the bare rule router.
    # When it does (e.g. the user's .env in this repo), router is wrapped
    # in a CompositeRouter. Both satisfy IntentRouter.
    from writer.routing import IntentRouter

    assert isinstance(deps.router, IntentRouter)

    action: AgentAction = deps.route("/init", "S0")
    assert action.action_type == "run_command"


def test_engine_init_defaults_to_current_directory(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.chdir(tmp_path)
    deps = production_deps()

    events = _consume(run_engine(_ctx("/init 引擎测试"), deps))

    assert (tmp_path / "引擎测试").is_dir()
    assert not (tmp_path / "novels" / "引擎测试").exists()
    done_events = [event for event in events if isinstance(event, Done)]
    assert done_events[-1].payload is not None
    assert done_events[-1].payload["project_root"] == str((tmp_path / "引擎测试").resolve())


def test_engine_init_brief_at_s1_writes_core_idea(tmp_path: Path) -> None:
    """Bound S1 project: ``/init <故事梗概>`` runs the creative brief flow."""

    deps = production_deps()
    workspace = create_workspace("创意项目", tmp_path)
    brief = (
        "林远穿越到了他写的游戏中。但他写的游戏是一个充满温馨故事的城市，"
        "然而他穿越到的这个世界是一个充满杀戮和罪恶的世界。"
    )

    events = _consume(run_engine(_workspace_ctx(f"/init {brief}", workspace.root), deps))

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))
    done_events = [e for e in events if isinstance(e, Done)]

    assert "已写入 创意/核心创意.md" in text_blob
    assert (workspace.root / "创意" / "核心创意.md").is_file()
    assert "## 基本要求" in (workspace.root / "AGENT.md").read_text(encoding="utf-8")
    assert done_events[-1].reason == "answered"
    assert done_events[-1].payload is not None
    assert done_events[-1].payload.get("init_brief") is True


def test_engine_init_brief_blocks_creative_text_at_s0(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """S0 + long creative pitch should steer user instead of creating a folder."""

    monkeypatch.chdir(tmp_path)
    deps = production_deps()
    brief = (
        "林远穿越到了他写的游戏中。但他写的游戏是一个充满温馨故事的城市，"
        "然而他穿越到的这个世界是一个充满杀戮和罪恶的世界。"
    )

    events = _consume(run_engine(_ctx(f"/init {brief}"), deps))

    assert not any(path.is_dir() for path in tmp_path.iterdir())
    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))
    done_events = [e for e in events if isinstance(e, Done)]

    assert "writer new <书名>" in text_blob
    assert done_events[-1].reason == "aborted"


# ---------------------------------------------------------------------------
# Wiring integration (Phase 2)
# ---------------------------------------------------------------------------


def test_engine_dispatches_outline_directive(tmp_path: Path) -> None:
    """``/大纲`` routes to the shipped ``/大纲`` Markdown directive (chg-markdown-skills).

    With no LLM configured the engine emits a TextChunk preview describing
    the directive and yields Done(reason="answered"). The directive body
    must surface somewhere in the streamed events so the user can see
    what the LLM would have done.
    """
    deps = production_deps()
    workspace = create_workspace("outline-test", tmp_path)

    events = _consume(
        run_engine(_workspace_ctx("/大纲 双主角女将军从冷宫到朝堂", workspace.root), deps)
    )

    action_events = [e for e in events if isinstance(e, ActionEvent)]
    done_events = [e for e in events if isinstance(e, Done)]
    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))

    assert any(
        isinstance(e, ActionEvent) and e.action.action_type == "run_command"
        for e in action_events
    )
    assert any(
        isinstance(e, ActionEvent) and e.action.command == "/大纲"
        for e in action_events
    )
    # Log line confirms directive dispatch
    assert "→ directive" in text_blob
    # Preview surfaces directive metadata
    assert "大纲" in text_blob
    answered = [e for e in done_events if e.reason == "answered"]
    assert answered, "expected at least one Done(reason='answered')"
    assert answered[0].payload.get("directive") == "/大纲"


def test_engine_dispatches_toc_directive(tmp_path: Path) -> None:
    """``/目录`` routes to the shipped ``/目录`` Markdown directive.

    Verifies the engine's directive dispatch path picks up the right
    directive based on the action's command and emits the expected
    log line + Done(reason="answered") event.
    """
    deps = production_deps()
    workspace = create_workspace("toc-test", tmp_path)
    (workspace.root / "大纲" / "大纲.md").write_text(
        "# 测试书名\n\n## 四幕大纲\n\n"
        "- 第一幕：开端\n"
        "- 第二幕：对抗\n"
        "- 第三幕：转折\n"
        "- 第四幕：终局\n",
        encoding="utf-8",
    )

    events = _consume(
        run_engine(_workspace_ctx("/目录", workspace.root), deps)
    )

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))
    done_events = [e for e in events if isinstance(e, Done)]

    # Log line confirms directive dispatch
    assert "→ directive" in text_blob
    answered = [e for e in done_events if e.reason == "answered"]
    assert answered, "expected Done(reason='answered')"
    assert answered[0].payload.get("directive") == "/目录"


def test_engine_streams_workflow_stub_chunks(tmp_path: Path) -> None:
    """``start_workflow`` must dispatch to the registered LangGraph workflow."""
    deps = _deps_with_real_prose()
    workspace = create_workspace("workflow-test", tmp_path)
    (workspace.root / "大纲" / "章节目录.md").write_text("第一章", encoding="utf-8")

    events = _consume(run_engine(_workspace_ctx("/创作 1.3", workspace.root), deps))

    text_blob = "".join(e.text for e in events if isinstance(e, TextChunk))

    assert "[workflow] LangGraph write_chapter 图完成" in text_blob
    assert "prep_context" in text_blob
    assert "review_gate" in text_blob
    # PR1: same as above — workflow_completed is the new terminal reason.
    assert any(isinstance(e, Done) and e.reason == "workflow_completed" for e in events)


def test_engine_workflow_unknown_name_raises_domain_error() -> None:
    """Unknown workflow names should raise WorkflowNotFoundError, not return a placeholder chunk.

    Per arch-optimizer m18 (2026-07-05): the previous behavior of
    returning a ``[workflow] 未知工作流 ...`` chunk looked like a
    legitimate workflow response to the user. Now the engine surfaces
    it as a ``ToolError`` via the existing ``except ToolError`` branch
    in ``_engine_loop`` -> ``ErrorEvent`` + ``Done(aborted)``.
    """
    from pathlib import Path

    import pytest

    from writer.agents import builtin_agent_registry
    from writer.engine.deps import _DefaultEngineDeps
    from writer.routing import RuleBasedIntentRouter
    from writer.skills import built_directive_registry
    from writer.tools import ToolRuntime, built_tool_registry
    from writer.tools.errors import WorkflowNotFoundError

    deps = _DefaultEngineDeps(
        router=RuleBasedIntentRouter(),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
        directive_registry=built_directive_registry(),
        agent_registry=builtin_agent_registry(),
        _workflows={},
    )

    with pytest.raises(WorkflowNotFoundError) as exc_info:
        deps.run_workflow("not_a_real_workflow", _ctx("ignored"))

    assert "not_a_real_workflow" in str(exc_info.value)


def test_production_deps_includes_all_registered_workflows() -> None:
    """production_deps() must register every workflow in writer.workflows.WORKFLOWS."""
    from writer.workflows import WORKFLOWS, WorkflowResult

    deps = _deps_with_real_prose()

    for name in WORKFLOWS:
        result = deps.run_workflow(name, _ctx("ignored"))
        # PR1: ``run_workflow`` returns a ``WorkflowResult``. Each
        # registered workflow must produce at least one chunk so the
        # engine has something to stream to the CLI.
        assert isinstance(result, WorkflowResult), (
            f"workflow {name!r} must return a WorkflowResult"
        )
        assert result.chunks, f"workflow {name!r} produced no chunks"


# ---------------------------------------------------------------------------
# Phase 3: Engine Loop branch wiring (add-llm-and-complete-engine-loop)
# ---------------------------------------------------------------------------


class _FailingRouter:
    """Stand-in router that raises on every call."""

    def route(self, user_input: str, project_state: str):  # type: ignore[no-untyped-def]
        raise RuntimeError("router kaboom")


class _AskUserRouter:
    """Stand-in router that always returns an ask_user action."""

    def __init__(self, prompt: str = "你想修改哪一段？") -> None:
        self._prompt = prompt

    def route(self, user_input: str, project_state: str) -> AgentAction:
        return AgentAction(action_type="ask_user", user_prompt=self._prompt)


def test_engine_emits_error_event_on_router_failure() -> None:
    from writer.agents import builtin_agent_registry
    from writer.engine import ErrorEvent
    from writer.engine.deps import _DefaultEngineDeps
    from writer.skills import built_directive_registry
    from writer.tools import ToolRuntime, built_tool_registry

    deps = _DefaultEngineDeps(
        router=_FailingRouter(),  # type: ignore[arg-type]
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
        directive_registry=built_directive_registry(),
        agent_registry=builtin_agent_registry(),
    )

    events = _consume(run_engine(_ctx("anything"), deps))

    assert any(isinstance(e, ErrorEvent) and "kaboom" in e.message for e in events)
    assert any(isinstance(e, Done) and e.reason == "aborted" for e in events)


def test_engine_emits_interrupt_for_ask_user_action() -> None:
    from writer.agents import builtin_agent_registry
    from writer.engine import Interrupt
    from writer.engine.deps import _DefaultEngineDeps
    from writer.skills import built_directive_registry
    from writer.tools import ToolRuntime, built_tool_registry

    deps = _DefaultEngineDeps(
        router=_AskUserRouter("你想修改哪一段？"),  # type: ignore[arg-type]
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
        directive_registry=built_directive_registry(),
        agent_registry=builtin_agent_registry(),
    )

    events = _consume(run_engine(_ctx("模糊输入"), deps))

    interrupts = [e for e in events if isinstance(e, Interrupt)]
    assert interrupts, "expected an Interrupt event"
    assert interrupts[0].type == "text"
    assert "哪一段" in interrupts[0].prompt
    assert any(isinstance(e, Done) and e.reason == "ask_user" for e in events)


def test_engine_fast_mode_suppresses_engine_log_chunks() -> None:
    from writer.agents import builtin_agent_registry
    from writer.engine import TextChunk
    from writer.engine.config import EngineConfig
    from writer.engine.deps import _DefaultEngineDeps
    from writer.skills import built_directive_registry
    from writer.tools import ToolRuntime, built_tool_registry

    deps = _DefaultEngineDeps(
        router=RuleBasedIntentRouter(),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
        directive_registry=built_directive_registry(),
        agent_registry=builtin_agent_registry(),
    )

    cfg = EngineConfig(session_id="x", fast_mode=True)
    events = _consume(run_engine(_ctx("帮我润色下这段"), deps, config=cfg))

    # No diagnostic TextChunks starting with [engine]
    engine_logs = [
        e
        for e in events
        if isinstance(e, TextChunk) and e.text.startswith("[engine]")
    ]
    assert engine_logs == []

    # Business events still present
    assert any(isinstance(e, ActionEvent) for e in events)
    assert any(isinstance(e, Done) and e.reason == "answered" for e in events)


def test_engine_calls_tool_registry_on_call_tool_action() -> None:
    """Real call_tool path: registry invoked, ToolCall + ToolResult + tool_completed emitted."""
    from writer.agents import builtin_agent_registry
    from writer.engine import ToolCall, ToolResult
    from writer.engine.deps import _DefaultEngineDeps
    from writer.skills import built_directive_registry
    from writer.tools import ToolRuntime, built_tool_registry

    deps = _DefaultEngineDeps(
        router=RuleBasedIntentRouter(),
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
        directive_registry=built_directive_registry(),
        agent_registry=builtin_agent_registry(),
    )

    events = _consume(run_engine(_ctx("查一下 F003"), deps))

    assert any(isinstance(e, ToolCall) and e.name == "foreshadow_search" for e in events)
    tool_results = [e for e in events if isinstance(e, ToolResult)]
    assert tool_results, "expected ToolResult event"
    assert tool_results[0].name == "foreshadow_search"
    assert tool_results[0].output  # non-empty result
    assert any(isinstance(e, Done) and e.reason == "tool_completed" for e in events)


def test_engine_handles_tool_not_found_error() -> None:
    """A tool name that the registry doesn't know must yield ErrorEvent + Done(aborted)."""
    from writer.agents import builtin_agent_registry
    from writer.engine import ErrorEvent
    from writer.engine.deps import _DefaultEngineDeps
    from writer.routing import AgentAction
    from writer.skills import built_directive_registry
    from writer.tools import ToolRuntime, built_tool_registry

    class _CallUnknownTool:
        def route(self, user_input: str, project_state: str) -> AgentAction:
            return AgentAction(
                action_type="call_tool",
                tool_name="definitely_not_a_tool",
            )

    deps = _DefaultEngineDeps(
        router=_CallUnknownTool(),  # type: ignore[arg-type]
        tool_registry=built_tool_registry(),
        tool_runtime=ToolRuntime(project_root=Path("/__no_project__")),
        directive_registry=built_directive_registry(),
        agent_registry=builtin_agent_registry(),
    )

    events = _consume(run_engine(_ctx("anything"), deps))

    assert any(isinstance(e, ErrorEvent) and "definitely_not_a_tool" in e.message for e in events)
    assert any(isinstance(e, Done) and e.reason == "aborted" for e in events)
