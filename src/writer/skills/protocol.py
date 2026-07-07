"""Skill protocol — composable command handlers for the engine."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import TYPE_CHECKING, Protocol, runtime_checkable

from writer.engine.config import EngineConfig
from writer.engine.context import EngineContext
from writer.engine.events import Done, TextChunk

if TYPE_CHECKING:
    from writer.engine.deps import EngineDeps


@runtime_checkable
class Skill(Protocol):
    """A reusable command handler invoked by the engine loop."""

    command: str

    def run(
        self,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        ...


__all__ = ["Skill"]
