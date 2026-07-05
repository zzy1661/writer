"""In-process tool registry.

The registry is the single source of truth for which tools the engine /
LangGraph can dispatch to. It enforces name uniqueness on register and
raises ``ToolNotFoundError`` on lookup miss.
"""

from __future__ import annotations

from collections.abc import Iterable

from writer.tools.errors import ToolNotFoundError
from writer.tools.protocol import Tool, ToolResult
from writer.tools.runtime import ToolRuntime


class ToolRegistry:
    """A name-indexed collection of tools.

    Construct empty, then ``.register()`` one tool at a time, or pass the
    full set via the constructor. Duplicate names raise ``ValueError``
    so misconfiguration surfaces at startup, not on the first call.
    """

    def __init__(self, *, tools: Iterable[Tool] = ()) -> None:
        self._tools: dict[str, Tool] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: Tool) -> ToolRegistry:
        """Add ``tool`` under its declared name. Chainable."""
        if tool.name in self._tools:
            msg = f"工具重复注册: {tool.name!r}"
            raise ValueError(msg)
        self._tools[tool.name] = tool
        return self

    def unregister(self, name: str) -> None:
        """Drop a tool by name. Missing names are silently ignored
        (the absence is already evidence the registry has been mutated)."""

        self._tools.pop(name, None)

    def get(self, name: str) -> Tool:
        if name not in self._tools:
            raise ToolNotFoundError(f"未注册工具: {name!r}")
        return self._tools[name]

    def has(self, name: str) -> bool:
        return name in self._tools

    def names(self) -> list[str]:
        return sorted(self._tools)

    def __len__(self) -> int:
        return len(self._tools)

    def __contains__(self, name: object) -> bool:
        return isinstance(name, str) and name in self._tools

    def invoke(
        self, name: str, runtime: ToolRuntime, /, **kwargs: object
    ) -> ToolResult:
        """Resolve and run ``name`` against ``runtime``.

        Positional-only ``runtime`` keeps call sites unambiguous
        (``registry.invoke(\"x\", runtime, path=\"…\")``).
        """

        return self.get(name).run(runtime, **kwargs)


__all__ = ["ToolRegistry"]
