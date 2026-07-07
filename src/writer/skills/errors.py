"""Domain exceptions raised by Skills.

Kept separate from the protocol so skill implementations, the engine
boundary, and consumers can import them without dragging in the heavier
engine event types. Symmetric with :mod:`writer.tools.errors` (the
boundary that the engine loop also catches — see ``_engine_loop`` in
:mod:`writer.engine.loop`).
"""

from __future__ import annotations


class SkillError(Exception):
    """Base class for recoverable failures inside a ``Skill.run()`` body.

    The engine boundary in :func:`writer.engine.loop._engine_loop`
    catches this specifically (after ``ToolError``) and surfaces the
    failure as an ``ErrorEvent`` followed by ``Done(reason='aborted')``
    with ``payload={'error': str(exc), 'command': <slash>}`` so the
    REPL can render a clean red ✗ marker plus the rejected command.

    Skills should raise :class:`SkillError` (or a subclass) for any
    condition that the user can recover from — missing project root,
    unsatisfied preconditions, malformed arguments. Truly unexpected
    bugs (ValueError / KeyError from inside the implementation) bubble
    up unchanged so the engine's catch-all ``except Exception`` arm
    still produces an ErrorEvent.
    """


__all__ = ["SkillError"]
