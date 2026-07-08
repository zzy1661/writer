"""Unit tests for EngineSession cross-turn state container."""

from __future__ import annotations

from collections.abc import Iterable
from pathlib import Path
from uuid import UUID

from writer.config import get_settings
from writer.engine import Interrupt
from writer.engine.context import EngineContext
from writer.engine.deps import EngineDeps
from writer.roles import HistoryConsultant, StoryConsultant, XuanhuanConsultant
from writer.routing import AgentAction, IntentRouter, RuleBasedIntentRouter
from writer.session import EngineSession, TurnRecord, compose_pending_input
from writer.skills import DirectiveRegistry, built_directive_registry
from writer.tools import ToolRuntime, built_tool_registry

# ---------------------------------------------------------------------------
# Identity & defaults
# ---------------------------------------------------------------------------


def test_session_fixes_session_id_across_turns() -> None:
    session = EngineSession()
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
    session = EngineSession()
    assert isinstance(session.session_id, UUID)


def test_session_started_at_is_datetime() -> None:
    from datetime import datetime

    session = EngineSession()
    assert isinstance(session.started_at, datetime)


def test_session_defaults() -> None:
    session = EngineSession()

    assert session.project_root is None
    assert session.project_state == "S0"
    assert session.project_genre == "other"
    assert session.turns == []
    assert session.pending_interrupt is None


# ---------------------------------------------------------------------------
# deps ownership
# ---------------------------------------------------------------------------


def test_session_deps_built_once_at_construction() -> None:
    s1 = EngineSession()
    s2 = EngineSession()
    deps1 = s1.deps
    deps2 = s2.deps

    # Each session owns its own deps
    assert deps1 is not deps2
    assert isinstance(deps1.router, IntentRouter)

    # Deps identity is stable across calls within the same session
    assert s1.deps is deps1


def test_session_deps_router_is_intent_router() -> None:
    session = EngineSession()
    assert isinstance(session.deps.router, IntentRouter)


# ---------------------------------------------------------------------------
# project_root swap
# ---------------------------------------------------------------------------


def test_session_tool_runtime_rebuilt_when_project_root_changes(
    tmp_path: Path,
) -> None:
    session = EngineSession()
    original_router = session.deps.router
    original_runtime = session.deps.tool_runtime

    session.set_project_root(tmp_path)

    assert session.project_root == tmp_path
    # Router preserved
    assert session.deps.router is original_router
    # ToolRuntime swapped to one pointing at the new root
    assert session.deps.tool_runtime is not original_runtime
    assert session.deps.tool_runtime.project_root == tmp_path.resolve()


def test_session_persists_project_root_across_turns(tmp_path: Path) -> None:
    session = EngineSession()
    session.set_project_root(tmp_path)
    after_id = id(session.deps)

    session.record_turn("hello", "answered")

    assert session.project_root == tmp_path
    assert id(session.deps) == after_id  # no rebuild on record_turn


def test_session_set_project_root_to_none_uses_sentinel() -> None:
    session = EngineSession()
    session.set_project_root(Path("/tmp/x"))
    session.set_project_root(None)

    assert session.project_root is None
    assert session.deps.tool_runtime.project_root == Path("/__no_project__").resolve()


def test_session_set_project_root_same_path_is_noop(tmp_path: Path) -> None:
    session = EngineSession()
    session.set_project_root(tmp_path)
    runtime_after_first = session.deps.tool_runtime

    session.set_project_root(tmp_path)  # same path
    assert session.deps.tool_runtime is runtime_after_first


def test_session_set_project_root_rebuilds_story_consultant_on_genre_change(
    tmp_path: Path,
) -> None:
    """Switching projects across genres must rebuild ``deps.story_consultant``.

    Per arch-optimizer M1 (2026-07-07): the old code only refreshed
    ``session.project_genre`` (the field) but never rebuilt ``deps
    .story_consultant`` (the instance). This test pins the new
    contract — a REPL session that runs ``/init 历史`` then ``/init
    玄幻`` ends up with an :class:`XuanhuanConsultant` in deps, not
    the stale :class:`HistoryConsultant` from the previous project.
    """

    def _seed_genre(root: Path, genre: str) -> None:
        root.mkdir(parents=True, exist_ok=True)
        (root / "AGENT.md").write_text(
            f"# novel\n\n## 当前状态\n\n- state: S1\n"
            f"- label: 初始化\n- 题材: {genre}\n\n",
            encoding="utf-8",
        )

    history_root = tmp_path / "history"
    xuanhuan_root = tmp_path / "xuanhuan"
    _seed_genre(history_root, "历史")
    _seed_genre(xuanhuan_root, "玄幻")

    session = EngineSession()
    session.set_project_root(history_root)
    assert isinstance(
        session.deps.story_consultant, HistoryConsultant
    ), f"expected HistoryConsultant, got {type(session.deps.story_consultant).__name__}"

    session.set_project_root(xuanhuan_root)
    assert isinstance(
        session.deps.story_consultant, XuanhuanConsultant
    ), (
        f"expected XuanhuanConsultant after switching genres, "
        f"got {type(session.deps.story_consultant).__name__}"
    )


# ---------------------------------------------------------------------------
# Turn history
# ---------------------------------------------------------------------------


def test_session_records_each_turn() -> None:
    session = EngineSession()

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
    session = EngineSession()
    for i in range(5):
        session.record_turn(f"input {i}", "answered")

    assert [r.turn_index for r in session.turns] == [0, 1, 2, 3, 4]


# ---------------------------------------------------------------------------
# Pending Interrupt lifecycle
# ---------------------------------------------------------------------------


def test_session_pending_interrupt_cleared_after_done() -> None:
    session = EngineSession()

    intr = Interrupt(type="text", prompt="你想修改哪一段？")
    session.set_pending_interrupt(intr)
    assert session.pending_interrupt is intr

    session.clear_pending_interrupt()
    assert session.pending_interrupt is None


def test_session_pending_interrupt_persists_until_cleared() -> None:
    session = EngineSession()
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

    assert _mod.EngineSession is EngineSession
    assert _mod.TurnRecord is TurnRecord
    assert _mod.compose_pending_input is compose_pending_input


# ---------------------------------------------------------------------------
# Protocol-only EngineDeps (arch-optimizer N9, 2026-07-05)
# ---------------------------------------------------------------------------


def test_session_set_project_root_with_protocol_only_deps(tmp_path: Path) -> None:
    """A non-dataclass ``EngineDeps`` implementation must survive ``set_project_root``.

    Per arch-optimizer N9 (2026-07-05): M6 added ``rebind_tool_runtime``
    to the ``EngineDeps`` Protocol so we no longer duck-type
    ``is_dataclass(self.deps)`` inside ``set_project_root``. This test
    verifies the new contract: a plain class (NOT ``@dataclass``)
    implementing all 4 fields + 3 methods of ``EngineDeps`` can be
    injected into ``EngineSession`` and ``set_project_root`` swaps
    ``tool_runtime`` cleanly.

    The old code skipped the duck-typed branch and rebuilt the whole
    production_deps (losing router / story_consultant) for any
    Protocol-only stub — the test below would have failed before M6.
    """

    class PlainDeps:
        """Plain (non-dataclass) ``EngineDeps`` implementation."""

        def __init__(self) -> None:
            self.router = RuleBasedIntentRouter()
            self.story_consultant = StoryConsultant(get_settings())
            self.tool_registry = built_tool_registry()
            self.tool_runtime = ToolRuntime(
                project_root=Path("/__no_project__").resolve()
            )
            self.directive_registry = built_directive_registry()
            # Required by the :class:`EngineDeps` Protocol since the
            # 2026-07-08 LLM tool-loop addition (``deps.tool_loop``).
            self.tool_loop = None

        def route(self, user_input: str, project_state: str) -> AgentAction:
            return self.router.route(user_input, project_state)

        def run_workflow(self, name: str, ctx: EngineContext) -> Iterable[str]:
            return []

        def rebind_tool_runtime(self, new_runtime: ToolRuntime) -> EngineDeps:
            self.tool_runtime = new_runtime
            return self

        def rebind_story_consultant(
            self, new_consultant: StoryConsultant
        ) -> EngineDeps:
            # Mirror M1's production wiring: in-place mutation is
            # allowed by the Protocol. The session-level test below
            # asserts this method is *called* during set_project_root,
            # not that it returns a new object.
            self.story_consultant = new_consultant
            return self

        def rebind_directive_registry(
            self, new_registry: DirectiveRegistry
        ) -> EngineDeps:
            # Added 2026-07-08 (chg-project-skills). The session's
            # ``set_project_root`` calls this after rebuilding the
            # registry; the stub mirrors the production wiring by
            # mutating in place.
            self.directive_registry = new_registry
            return self

    # The stub satisfies the ``@runtime_checkable`` EngineDeps Protocol.
    stub = PlainDeps()
    assert isinstance(stub, EngineDeps)

    # Inject into session (skip the default production_deps construction).
    session = EngineSession()
    session.deps = stub
    original_router = session.deps.router

    # ``set_project_root`` must NOT raise ``AttributeError`` (regression
    # on M6: the old duck-typed branch needed ``is_dataclass(self.deps)``).
    session.set_project_root(tmp_path)

    assert session.project_root == tmp_path
    # Router preserved across the swap (no full production_deps rebuild).
    assert session.deps.router is original_router
    # Runtime swapped to the new root.
    assert session.deps.tool_runtime.project_root == tmp_path.resolve()


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
    session = EngineSession()
    session.project_root = tmp_path

    result = session.refresh_project_genre()
    assert result == "言情"
    assert session.project_genre == "言情"


def test_session_refresh_project_genre_falls_back_when_missing_ticaline(
    tmp_path: Path,
) -> None:
    _seed_agent_md(tmp_path, genre=None)
    session = EngineSession()

    assert session.refresh_project_genre() == "other"
    assert session.project_genre == "other"


def test_session_refresh_project_genre_falls_back_when_agent_md_missing(
    tmp_path: Path,
) -> None:
    session = EngineSession()

    assert session.refresh_project_genre() == "other"
    assert session.project_genre == "other"


def test_session_set_project_root_triggers_genre_refresh(tmp_path: Path) -> None:
    _seed_agent_md(tmp_path, genre="玄幻")
    session = EngineSession()

    session.set_project_root(tmp_path)

    assert session.project_genre == "玄幻"
