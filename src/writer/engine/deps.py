"""Dependency injection boundary for the agent engine.

The engine never instantiates its collaborators directly — every external
boundary is declared here as a ``Protocol``. This matches Claude Code §十
"最小接口 DI": we only inject what gets swapped (tests, alternate
dispatchers, future LLM-backed implementations).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from writer.agent.command_agent import AgentAction, WriterCommandAgent


@runtime_checkable
class EngineDeps(Protocol):
    """Minimum surface the engine loop depends on.

    Future expansion points (intentionally not declared yet):
    * ``tool_registry``: ToolRegistry (per 备忘 13)
    * ``workflow_starter``: WorkflowStarter (per 备忘 04)
    * ``interrupt_handler``: InterruptHandler (per 备忘 14)
    * ``stop_hooks``: StopHookRegistry (Claude Code §十二·12.3)
    """

    dispatcher: WriterCommandAgent

    def decide(self, user_input: str, project_state: str) -> AgentAction:
        ...


@dataclass
class _DefaultEngineDeps:
    """Production wiring with the rule-based dispatcher.

    Defined as a dataclass rather than a hand-written class so adding
    fields later (tool registry, workflow starter, …) is a one-line
    change instead of a constructor rewrite.
    """

    dispatcher: WriterCommandAgent

    def decide(self, user_input: str, project_state: str) -> AgentAction:
        return self.dispatcher.decide(user_input, project_state)


def production_deps() -> EngineDeps:
    """Default dependency wiring used by the REPL and tests."""
    return _DefaultEngineDeps(dispatcher=WriterCommandAgent())


__all__ = ["EngineDeps", "production_deps"]
