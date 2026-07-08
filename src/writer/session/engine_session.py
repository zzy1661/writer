"""Cross-turn session state container.

The ``EngineSession`` is created once at REPL startup and reused for every
turn. It owns:

- **Identity** (frozen): ``session_id`` (UUID) and ``started_at`` (datetime).
- **Project context** (mutable): ``project_root`` (Path | None) and the
  latest state detected from disk.
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
    project_state: str = "S0"
    project_genre: str = "other"

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

            if self.project_root is not None:
                # Production-deps is now a pure factory (M2 2026-07-08) —
                # it no longer reads AGENT.md behind the caller's back,
                # so we refresh ``project_genre`` here and pass it down.
                self.refresh_project_genre()
            # ``production_deps`` is responsible for also wiring
            # ``skill_registry`` with the bound project (per
            # chg-project-skills) so the very first ``/大纲`` etc.
            # lookup sees the project-level overrides. We do NOT
            # post-hoc rebuild here — the session's
            # ``set_project_root`` handles later project changes.
            self.deps = production_deps(
                project_root=self.project_root,
                genre=self.project_genre,
            )

    # ------------------------------------------------------------------
    # project_root + deps management
    # ------------------------------------------------------------------

    def set_project_root(self, new_root: Path | None) -> None:
        """Update ``project_root`` and rebuild ``deps``-level collaborators.

        Router / tool_registry are preserved across the swap.
        ``tool_runtime`` is rebuilt because it holds the project_root
        that gates ``safe_path`` checks. ``story_consultant`` is ALSO
        rebuilt if the bound project's ``AGENT.md`` ``题材:`` line
        resolves to a different Consultant subclass (per arch-optimizer
        M1, 2026-07-07): without this rebuild, a REPL session that
        runs ``/init 历史`` then ``/init 玄幻`` would keep the
        HistoryConsultant in deps and serve stale outlines.

        ``skill_registry`` is also rebuilt (per ``chg-project-skills``)
        so the new project's ``.writer/skills/`` overrides become
        visible on the next REPL turn.

        Setting ``new_root`` to the same path is a no-op (no rebuild).
        Setting ``new_root=None`` falls back to the S0 sentinel root.

        The actual swaps go through :meth:`EngineDeps.rebind_*` so we
        never need to know whether the concrete ``EngineDeps`` is a
        dataclass, a plain object, or a test fake.
        """

        if new_root == self.project_root:
            return

        from writer.config import get_settings
        from writer.engine.deps import _consultant_for_genre
        from writer.skills import built_skill_registry
        from writer.tools import ToolRuntime

        if new_root is not None:
            from writer.config import load_env_file, refresh_settings

            load_env_file(new_root)
            refresh_settings()

        self.project_root = new_root
        resolved = (new_root or _SENTINEL_PROJECT_ROOT).resolve()
        new_runtime = ToolRuntime(project_root=resolved)
        self.deps = self.deps.rebind_tool_runtime(new_runtime)
        self.refresh_project_state()
        self.refresh_project_genre()

        # Rebuild story_consultant against the freshly-read genre. Uses
        # the same Settings the deps were originally built with so
        # LLM/feature flags stay consistent across the swap.
        new_consultant = _consultant_for_genre(
            get_settings(), self.project_genre
        )
        self.deps = self.deps.rebind_story_consultant(new_consultant)

        # Rebuild the skill registry so the new project's
        # ``.writer/skills/`` overrides take effect on the next turn.
        # ``built_skill_registry`` is invoked with the resolved
        # sentinel (not ``None``) for S0 so any future S0 skill stub
        # can rely on a real path; in practice the sentinel is not a
        # directory so ``discover_project_skills`` returns ``[]``.
        new_registry = built_skill_registry(project_root=resolved)
        self.deps = self.deps.rebind_skill_registry(new_registry)

    def refresh_project_state(self) -> str:
        """Refresh ``project_state`` from files on disk and return it."""

        from writer.project import detect_state

        self.project_state = detect_state(self.project_root).value
        return self.project_state

    def refresh_project_genre(self) -> str:
        """Refresh ``project_genre`` from ``(project_root / AGENT.md)``.

        Returns the refreshed value (``"other"`` when missing or empty).
        The method never raises — a torn AGENT.md just falls back to
        ``"other"``. Called automatically from
        :meth:`set_project_root` and on demand by callers that want to
        re-read after an external ``AGENT.md`` edit.
        """

        if self.project_root is None:
            self.project_genre = "other"
        else:
            from writer.project import read_genre_from_agent

            self.project_genre = read_genre_from_agent(
                self.project_root / "AGENT.md"
            )
        return self.project_genre

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
