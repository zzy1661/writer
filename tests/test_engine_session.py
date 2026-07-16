"""Unit tests for Engine cross-turn state container."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from writer.agents import builtin_agent_registry
from writer.config import get_settings
from writer.llm.prose import DeterministicProseClient
from writer.routing import AgentAction, IntentRouter, RuleBasedIntentRouter
from writer.runner import Interrupt, Runner
from writer.runner.context import RunnerContext
from writer.runner.deps import RunnerDeps
from writer.session import Engine, TurnRecord, compose_pending_input
from writer.skills import DirectiveRegistry, built_directive_registry
from writer.tools import ToolRuntime, built_tool_registry
from writer.workflows.types import WorkflowResult

# ---------------------------------------------------------------------------
# Identity & defaults
# ---------------------------------------------------------------------------


def test_session_fixes_session_id_across_turns() -> None:
    session = Engine()
    initial_id = session.session_id

    # Multiple records keep the same session_id
    session.record_turn("a", "answered")
    session.record_turn("b", "tool_completed")
    session.record_turn("c", "aborted")

    assert all(isinstance(r, TurnRecord) for r in session.turns)
    # session_id is stable across the session's lifetime
    assert session.session_id == initial_id
    session.record_turn("d", "answered")
    assert session.session_id == initial_id


def test_session_id_is_uuid() -> None:
    session = Engine()
    assert isinstance(session.session_id, UUID)


def test_session_started_at_is_datetime() -> None:
    from datetime import datetime

    session = Engine()
    assert isinstance(session.started_at, datetime)


def test_session_defaults() -> None:
    session = Engine()

    assert session.project_root is None
    assert session.project_state == "S0"
    assert session.project_genre == "other"
    assert session.turns == []
    assert session.pending_interrupt is None


# ---------------------------------------------------------------------------
# deps ownership
# ---------------------------------------------------------------------------


def test_session_deps_built_once_at_construction() -> None:
    s1 = Engine()
    s2 = Engine()
    deps1 = s1.runner.deps
    deps2 = s2.runner.deps

    # Each session owns its own deps
    assert deps1 is not deps2
    assert isinstance(deps1.router, IntentRouter)

    # Deps identity is stable across calls within the same session
    assert s1.runner.deps is deps1


def test_session_deps_router_is_intent_router() -> None:
    session = Engine()
    assert isinstance(session.runner.deps.router, IntentRouter)


# ---------------------------------------------------------------------------
# project_root swap
# ---------------------------------------------------------------------------


def test_session_tool_runtime_rebuilt_when_project_root_changes(
    tmp_path: Path,
) -> None:
    session = Engine()
    original_router = session.runner.deps.router
    original_runtime = session.runner.deps.tool_runtime

    session.set_project_root(tmp_path)

    assert session.project_root == tmp_path
    # Router preserved
    assert session.runner.deps.router is original_router
    # ToolRuntime swapped to one pointing at the new root
    assert session.runner.deps.tool_runtime is not original_runtime
    assert session.runner.deps.tool_runtime.project_root == tmp_path.resolve()


def test_session_persists_project_root_across_turns(tmp_path: Path) -> None:
    session = Engine()
    session.set_project_root(tmp_path)
    after_id = id(session.runner.deps)

    session.record_turn("hello", "answered")

    assert session.project_root == tmp_path
    assert id(session.runner.deps) == after_id  # no rebuild on record_turn


def test_session_set_project_root_to_none_uses_sentinel() -> None:
    session = Engine()
    session.set_project_root(Path("/tmp/x"))
    session.set_project_root(None)

    assert session.project_root is None
    assert session.runner.deps.tool_runtime.project_root == Path("/__no_project__").resolve()


def test_session_set_project_root_same_path_is_noop(tmp_path: Path) -> None:
    session = Engine()
    session.set_project_root(tmp_path)
    runtime_after_first = session.runner.deps.tool_runtime

    session.set_project_root(tmp_path)  # same path
    assert session.runner.deps.tool_runtime is runtime_after_first


# ---------------------------------------------------------------------------
# Turn history
# ---------------------------------------------------------------------------


def test_session_records_each_turn() -> None:
    session = Engine()

    r0 = session.record_turn("查 F003", "tool_completed")
    r1 = session.record_turn("帮我润色", "answered")

    assert len(session.turns) == 2
    assert r0.turn_index == 0
    assert r1.turn_index == 1
    assert r0.user_input == "查 F003"
    assert r1.user_input == "帮我润色"
    assert r0.done_reason == "tool_completed"
    assert r1.done_reason == "answered"


def test_session_turn_index_increments() -> None:
    session = Engine()
    for i in range(5):
        session.record_turn(f"input {i}", "answered")

    assert [r.turn_index for r in session.turns] == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Pending Interrupt lifecycle
# ---------------------------------------------------------------------------


def test_session_pending_interrupt_cleared_after_done() -> None:
    session = Engine()

    intr = Interrupt(type="text", prompt="你想修改哪一段？")
    session.set_pending_interrupt(intr)
    assert session.pending_interrupt is intr

    session.clear_pending_interrupt()
    assert session.pending_interrupt is None


def test_session_pending_interrupt_persists_until_cleared() -> None:
    session = Engine()
    intr = Interrupt(type="text", prompt="Q?")
    session.set_pending_interrupt(intr)

    # Multiple record_turn calls do NOT clear pending
    session.record_turn("a", "answered")
    session.record_turn("b", "answered")
    assert session.pending_interrupt is intr


def test_compose_pending_input_with_pending() -> None:
    intr = Interrupt(type="text", prompt="你想修改哪一段？")
    out = compose_pending_input("修第2段", intr)

    assert out.startswith("[pending] 你想修改哪一段？")
    assert "[answer] 修第2段" in out


def test_compose_pending_input_without_pending() -> None:
    out = compose_pending_input("查 F003", None)
    assert out == "查 F003"


# ---------------------------------------------------------------------------
# Public surface
# ---------------------------------------------------------------------------


def test_session_package_public_surface() -> None:
    import writer.session as _mod

    assert _mod.Engine is Engine
    assert _mod.TurnRecord is TurnRecord
    assert _mod.compose_pending_input is compose_pending_input


# ---------------------------------------------------------------------------
# Protocol-only RunnerDeps (arch-optimizer N9, 2026-07-05)
# ---------------------------------------------------------------------------


def test_session_set_project_root_with_protocol_only_deps(tmp_path: Path) -> None:
    """A non-dataclass ``RunnerDeps`` implementation must survive ``set_project_root``.

    Per arch-optimizer N9 (2026-07-05): M6 added ``rebind_tool_runtime``
    to the ``RunnerDeps`` Protocol so we no longer duck-type
    ``is_dataclass(self.deps)`` inside ``set_project_root``. This test
    verifies the new contract: a plain class (NOT ``@dataclass``)
    implementing all 5 fields + 4 methods of ``RunnerDeps`` can be
    injected into ``Engine`` and ``set_project_root`` swaps
    ``tool_runtime`` cleanly.

    Updated 2026-07-09 (``chg-remove-roles``): the
    ``rebind_story_agent`` method + ``story_agent`` field are gone
    (the ``writer.roles.StoryAgent`` class was deleted).
    """

    class PlainDeps:
        """Plain (non-dataclass) ``RunnerDeps`` implementation."""

        def __init__(self) -> None:
            self.router = RuleBasedIntentRouter()
            self.agent_registry = builtin_agent_registry()
            self.tool_registry = built_tool_registry()
            self.tool_runtime = ToolRuntime(
                project_root=Path("/__no_project__").resolve()
            )
            self.directive_registry = built_directive_registry()
            # Required by the :class:`RunnerDeps` Protocol since the
            # 2026-07-08 LLM tool-loop addition (``deps.tool_loop``).
            self.tool_loop = None
            # Required by the Protocol since 2026-07-09
            # (real-writing-pipeline PR2 — ``deps.prose_client``).
            # The session tests don't exercise prose; the
            # ``DeterministicProseClient`` is the safe default.
            self.prose_client = DeterministicProseClient()
            # PR2: ``deps.review_llm`` is an optional review-LLM
            # override (test surface). Leaving ``None`` makes the
            # workflow fall back to ``get_llm(settings)``.
            self.review_llm = None
            # Added 2026-07-09 (Bug 01). Required by Protocol so
            # ``set_project_root`` can rebuild ``tool_loop`` against
            # the same settings without re-resolving globals.
            self.settings = get_settings()

        def route(self, user_input: str, project_state: str) -> AgentAction:
            return self.router.route(user_input, project_state)

        def run_workflow(self, name: str, ctx: RunnerContext) -> WorkflowResult:
            # PR1: return a real WorkflowResult (no more Iterable[str]).
            # Default to completed so engine emits workflow_completed.
            return WorkflowResult(status="completed", chunks=())

        def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> RunnerDeps:
            self.tool_runtime = new_runtime
            return self

        def rebind_directive_registry(
            self, new_registry: DirectiveRegistry
        ) -> RunnerDeps:
            # Added 2026-07-08 (chg-project-skills). The session's
            # ``set_project_root`` calls this after rebuilding the
            # registry; the stub mirrors the production wiring by
            # mutating in place.
            self.directive_registry = new_registry
            return self

        def rebind_skill_registry(
            self, new_registry: DirectiveRegistry
        ) -> RunnerDeps:
            # Back-compat alias kept for the older name; the Protocol
            # declares both methods so existing callers still work.
            self.directive_registry = new_registry
            return self

        def rebind_agent_registry(
            self, new_registry: object
        ) -> RunnerDeps:
            # Added 2026-07-09 (fea-agent-mirror). Symmetric to
            # rebind_directive_registry: ``set_project_root`` calls
            # this after rebuilding the registry from the new
            # project's ``.writer/agents/``.
            self.agent_registry = new_registry
            return self

        def rebind_tool_loop(
            self, new_loop: object
        ) -> RunnerDeps:
            # Added 2026-07-09 (Bug 01). Symmetric to rebind_tool_runtime.
            # ``set_project_root`` calls this with a newly constructed
            # ``ReActAgent`` (or ``None`` for rule-only deployment).
            self.tool_loop = new_loop
            return self

    # The stub satisfies the ``@runtime_checkable`` RunnerDeps Protocol.
    stub = PlainDeps()
    assert isinstance(stub, RunnerDeps)

    # Inject into session (skip the default production_deps construction).
    session = Engine()
    session.runner = Runner(deps=stub)
    original_router = session.runner.deps.router

    # ``set_project_root`` must NOT raise ``AttributeError`` (regression
    # on M6: the old duck-typed branch needed ``is_dataclass(self.deps)``).
    session.set_project_root(tmp_path)

    assert session.project_root == tmp_path
    # Router preserved across the swap (no full production_deps rebuild).
    assert session.runner.deps.router is original_router
    # Runtime swapped to the new root.
    assert session.runner.deps.tool_runtime.project_root == tmp_path.resolve()


# ---------------------------------------------------------------------------
# Bug 01 — tool_loop rebind on set_project_root
# ---------------------------------------------------------------------------


def test_set_project_root_rebuilds_tool_loop(tmp_path: Path) -> None:
    """Bug 01: 当 deps 带 tool_loop 时,set_project_root 用新 runtime 重建。

    直接构造 production_deps(settings with API key) 让 tool_loop 被装配,
    然后 set_project_root(B),断言 deps.tool_loop._runtime 指向 B。
    """
    from pydantic import SecretStr

    from writer.config import Settings
    from writer.runner.deps import production_deps

    proj_a = tmp_path / "proj_a"
    proj_b = tmp_path / "proj_b"
    proj_a.mkdir()
    proj_b.mkdir()

    settings = Settings(
        model="gpt-4o-mini",
        api_key=SecretStr("sk-test"),
        base_url="https://api.openai.com/v1",
        temperature=0.0,
    )

    deps = production_deps(settings=settings, project_root=proj_a)
    assert deps.tool_loop is not None
    assert deps.tool_loop._runtime.project_root == proj_a.resolve()

    session = Engine()
    session.runner = Runner(deps=deps)
    session.project_root = proj_a

    # 切到 B:tool_loop 应被重建,新 runtime 指向 B
    session.set_project_root(proj_b)
    assert session.runner.deps.tool_loop is not None
    assert session.runner.deps.tool_loop._runtime.project_root == proj_b.resolve()


def test_set_project_root_with_protocol_only_deps(tmp_path: Path) -> None:
    """Bug 01: PlainDeps 补 rebind_tool_loop 后,set_project_root 通过。"""
    # PlainDeps 已有 rebind_tool_loop;这里只验证 isinstance(stub, RunnerDeps)
    # 仍然为真,确保 Protocol 字段扩展未破坏 stub 验证。
    stub_factory = _build_plain_deps_stub()  # type: ignore[func-returns-value]
    session = Engine()
    session.runner = Runner(deps=stub_factory)
    assert isinstance(session.runner.deps, RunnerDeps)
    # 调用 set_project_root 不抛 AttributeError
    session.set_project_root(tmp_path)
    assert session.runner.deps.tool_runtime.project_root == tmp_path.resolve()


def _build_plain_deps_stub() -> RunnerDeps:
    """返回一个最小 PlainDeps 实例,满足 RunnerDeps Protocol。"""
    # 直接复用类内测试的 stub 模式;最小字段集足以过 isinstance 检查。
    class _Stub:
        def __init__(self) -> None:
            self.router = RuleBasedIntentRouter()
            self.agent_registry = builtin_agent_registry()
            self.tool_registry = built_tool_registry()
            self.tool_runtime = ToolRuntime(
                project_root=Path("/__no_project__").resolve()
            )
            self.directive_registry = built_directive_registry()
            self.tool_loop = None
            self.prose_client = DeterministicProseClient()
            self.review_llm = None
            self.settings = get_settings()

        def route(self, user_input: str, project_state: str) -> AgentAction:
            return self.router.route(user_input, project_state)

        def run_workflow(self, name: str, ctx: RunnerContext) -> WorkflowResult:
            return WorkflowResult(status="completed", chunks=())

        def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> RunnerDeps:
            self.tool_runtime = new_runtime
            return self

        def rebind_directive_registry(
            self, new_registry: DirectiveRegistry
        ) -> RunnerDeps:
            self.directive_registry = new_registry
            return self

        def rebind_skill_registry(
            self, new_registry: DirectiveRegistry
        ) -> RunnerDeps:
            self.directive_registry = new_registry
            return self

        def rebind_agent_registry(self, new_registry: object) -> RunnerDeps:
            self.agent_registry = new_registry
            return self

        def rebind_tool_loop(self, new_loop: object) -> RunnerDeps:
            self.tool_loop = new_loop
            return self

    return _Stub()


def test_set_project_root_none_does_not_error(tmp_path: Path) -> None:
    """Bug 01: tool_loop 原本非 None,set_project_root(None) 不抛错。"""
    from pydantic import SecretStr

    from writer.config import Settings
    from writer.runner.deps import production_deps

    proj_a = tmp_path / "proj_a"
    proj_a.mkdir()

    settings = Settings(
        model="gpt-4o-mini",
        api_key=SecretStr("sk-test"),
        base_url="https://api.openai.com/v1",
        temperature=0.0,
    )
    deps = production_deps(settings=settings, project_root=proj_a)
    assert deps.tool_loop is not None

    session = Engine()
    session.runner = Runner(deps=deps)
    session.project_root = proj_a

    # 切到 None:不应抛错;tool_loop 仍指向 ReActAgent(因为 settings
    # 还有 API key);runtime 已切到 sentinel。
    session.set_project_root(None)
    # 不抛错,tool_runtime 已切到 sentinel
    assert session.runner.deps.tool_runtime.project_root == Path("/__no_project__").resolve()


# ---------------------------------------------------------------------------
# project_genre (fea-genre-aware-init Block 3)
# ---------------------------------------------------------------------------


def _seed_agent_md(root: Path, *, genre: str | None) -> None:
    root.mkdir(parents=True, exist_ok=True)
    (root / "AGENT.md").write_text(
        "# test\n\n## 当前状态\n\n- state: S1\n- label: 初始化\n"
        + (f"- 题材: {genre}\n" if genre else "")
        + "\n## 目录约定\n\n",
        encoding="utf-8",
    )


def test_session_refresh_project_genre_reads_agent_md(tmp_path: Path) -> None:
    _seed_agent_md(tmp_path, genre="言情")
    session = Engine()
    session.project_root = tmp_path

    result = session.refresh_project_genre()
    assert result == "言情"
    assert session.project_genre == "言情"


def test_session_refresh_project_genre_falls_back_when_missing_ticaline(
    tmp_path: Path,
) -> None:
    _seed_agent_md(tmp_path, genre=None)
    session = Engine()

    assert session.refresh_project_genre() == "other"
    assert session.project_genre == "other"


def test_session_refresh_project_genre_falls_back_when_agent_md_missing(
    tmp_path: Path,
) -> None:
    session = Engine()

    assert session.refresh_project_genre() == "other"
    assert session.project_genre == "other"


def test_session_set_project_root_triggers_genre_refresh(tmp_path: Path) -> None:
    _seed_agent_md(tmp_path, genre="玄幻")
    session = Engine()

    session.set_project_root(tmp_path)

    assert session.project_genre == "玄幻"
