"""Cross-turn session state container.

The ``EngineSession`` is created once at REPL startup and reused for every
turn. It owns:

- **Identity** (frozen): ``session_id`` (UUID) and ``started_at`` (datetime).
- **Project context** (mutable): ``project_root`` (Path | None) and
  ``project_state`` (str placeholder until ``detect_state()`` lands later).
- **deps** (mutable): the ``EngineDeps`` instance, built once at
  construction. ``tool_runtime`` is swapped via :meth:`set_project_root`
  while router / story_consultant / tool_registry are preserved.
- **turns** (mutable): append-only list of :class:`TurnRecord`.
- **pending_interrupt** (mutable): the most recent ``Interrupt`` event
  emitted by the engine, cleared when the next turn completes.

EngineSession does NOT replace the per-turn ``EngineContext`` — that stays
as the immutable input contract for ``run_engine``. EngineSession sits
*outside* the engine and feeds it one context per turn.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

if TYPE_CHECKING:
    from writer.engine.deps import EngineDeps
    from writer.engine.events import DoneReason, Interrupt


@dataclass(frozen=True)
class TurnRecord:
    """One turn's outcome: what the user said and how the engine ended."""

    turn_index: int
    user_input: str
    done_reason: DoneReason
    timestamp: datetime


_SENTINEL_PROJECT_ROOT = Path("/__no_project__")


@dataclass
class EngineSession:
    """Cross-turn session state container (per 备忘 16 line 374 reservation)."""

    # Frozen identity — set once at construction, never mutated.
    session_id: UUID = field(default_factory=uuid4)
    started_at: datetime = field(
        default_factory=lambda: datetime.now(UTC)
    )

    # Project context (mutable).
    project_root: Path | None = None
    project_state: str = "S0"  # placeholder until detect_state() lands

    # Deps — built once at construction; tool_runtime swap on project_root change.
    deps: EngineDeps = field(default=None)  # type: ignore[assignment]

    # Append-only turn history.
    turns: list[TurnRecord] = field(default_factory=list)

    # Pending Interrupt from the previous turn; cleared after consumption.
    pending_interrupt: Interrupt | None = None

    def __post_init__(self) -> None:
        # Lazy-import to avoid circular imports (engine.deps imports
        # writer.routing which is allowed to import nothing from session).
        if self.deps is None:
            from writer.engine.deps import production_deps

            self.deps = production_deps(project_root=self.project_root)

    # ------------------------------------------------------------------
    # project_root + deps management
    # ------------------------------------------------------------------

    def set_project_root(self, new_root: Path | None) -> None:
        """Update ``project_root`` and rebuild ``deps.tool_runtime``.

        Router / story_consultant / tool_registry are preserved across
        the swap. ``tool_runtime`` is rebuilt because it holds the
        project_root that gates ``safe_path`` checks.

        Setting ``new_root`` to the same path is a no-op (no rebuild).
        Setting ``new_root=None`` falls back to the S0 sentinel root.

        The actual swap goes through :meth:`EngineDeps.rebind_tool_runtime`
        (per arch-optimizer M6) so we never need to know whether the
        concrete ``EngineDeps`` is a dataclass, a plain object, or a
        test fake. Previously this method duck-typed
        ``is_dataclass(self.deps) and any(f.name == ...)`` and silently
        fell back to rebuilding the whole deps (losing router /
        story_consultant) when a test injected a Protocol-only stub.
        """

        if new_root == self.project_root:
            return

        from writer.tools import ToolRuntime

        self.project_root = new_root
        resolved = (new_root or _SENTINEL_PROJECT_ROOT).resolve()
        new_runtime = ToolRuntime(project_root=resolved)
        self.deps = self.deps.rebind_tool_runtime(new_runtime)

    # ------------------------------------------------------------------
    # Turn history
    # ------------------------------------------------------------------

    def record_turn(self, user_input: str, done_reason: DoneReason) -> TurnRecord:
        """Append a :class:`TurnRecord` and return it."""

        record = TurnRecord(
            turn_index=len(self.turns),
            user_input=user_input,
            done_reason=done_reason,
            timestamp=datetime.now(UTC),
        )
        self.turns.append(record)
        return record

    # ------------------------------------------------------------------
    # Pending Interrupt lifecycle
    # ------------------------------------------------------------------

    def set_pending_interrupt(self, interrupt: Interrupt) -> None:
        self.pending_interrupt = interrupt

    def clear_pending_interrupt(self) -> None:
        self.pending_interrupt = None


# ----------------------------------------------------------------------
# Module-level helpers
# ----------------------------------------------------------------------


def compose_pending_input(original: str, pending: Interrupt | None) -> str:
    """Return the user input string to feed the engine for a turn.

    If ``pending`` is set, the prompt is prepended with a visible marker
    so the LLM router sees both the prior question and the user's
    answer. When ``pending`` is ``None``, the original input is returned
    unchanged.

    The output is plain text — markers are bracketed so they remain
    visible in REPL logs and console prints.
    """

    if pending is None:
        return original
    return f"[pending] {pending.prompt}\n[answer] {original}"


__all__ = [
    "EngineSession",
    "TurnRecord",
    "compose_pending_input",
]
