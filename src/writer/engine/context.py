"""Input contract and mutable loop state for the agent engine."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class EngineContext:
    """Immutable input for a single engine turn.

    This mirrors Claude Code's per-turn ``Context`` contract: the engine
    never reaches outside this object for the turn's inputs. ``project_root``
    is left optional for the S0 (no project) path; ``project_state`` uses
    a string placeholder until the real state machine is wired in.
    """

    user_input: str
    project_root: Path | None = None
    project_state: str = "S0"
    session_id: str = ""


@dataclass
class EngineState:
    """Mutable per-turn state shared across loop iterations.

    ``transition`` records why the previous iteration asked to ``continue``
    — useful for error recovery hooks planned for later iterations.
    """

    ctx: EngineContext
    transition: str | None = None


__all__ = ["EngineContext", "EngineState"]
