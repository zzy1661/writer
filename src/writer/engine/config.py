"""Frozen environment snapshot for a single engine turn."""

from __future__ import annotations

from dataclasses import dataclass

from writer.engine.context import EngineContext


@dataclass(frozen=True)
class EngineConfig:
    """Immutable runtime knobs captured once per turn.

    Mirrors Claude Code §八 "环境冰封": config does not change mid-turn,
    so consumers can rely on its values when interpreting the event stream.
    """

    session_id: str
    fast_mode: bool = False


def build_engine_config(
    ctx: EngineContext, *, fast_mode: bool = False
) -> EngineConfig:
    """Snapshot the engine config from the context + runtime overrides."""

    return EngineConfig(session_id=ctx.session_id, fast_mode=fast_mode)


__all__ = ["EngineConfig", "build_engine_config"]
