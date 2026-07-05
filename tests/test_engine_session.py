"""Unit tests for EngineSession cross-turn state container."""

from __future__ import annotations

from pathlib import Path
from uuid import UUID

from writer.engine import Interrupt
from writer.routing import IntentRouter
from writer.session import EngineSession, TurnRecord, compose_pending_input

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
