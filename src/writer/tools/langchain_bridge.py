"""Bridge from writer ``Tool`` objects to LangChain ``BaseTool``.

When LangGraph's ``ToolNode`` arrives (per 04) it will expect a list of
LangChain ``BaseTool`` instances. This adapter produces them on demand
without requiring every writer tool to also be a ``BaseTool`` subclass.

The returned tool captures ``runtime`` in a closure, so a single
registry can produce session-specific base tools in one call. Each
wrapper also generates a typed ``args_schema`` from the writer tool's
``run`` signature, which is the only reliable way to make LangChain
unpack the input dict back into kwargs.
"""

from __future__ import annotations

import inspect
from typing import TYPE_CHECKING, Any

from langchain_core.tools import BaseTool, StructuredTool
from pydantic import BaseModel, Field, create_model

from writer.tools.runtime import ToolRuntime

if TYPE_CHECKING:
    from writer.tools.protocol import Tool
    from writer.tools.registry import ToolRegistry


def _build_args_schema(writer_tool: "Tool") -> type[BaseModel] | None:
    """Derive a Pydantic v2 model from a writer tool's ``run`` signature.

    Skips ``self`` and ``runtime`` (the latter is captured in the closure
    of the bridge). All remaining keyword arguments become typed fields;
    defaults are preserved if the writer supplied one.
    """

    sig = inspect.signature(writer_tool.run)
    fields: dict[str, Any] = {}
    skip = {"self", "runtime"}

    for name, param in sig.parameters.items():
        if name in skip:
            continue
        if param.kind not in (
            inspect.Parameter.KEYWORD_ONLY,
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
        ):
            continue
        annotation = (
            param.annotation if param.annotation is not inspect.Parameter.empty else Any
        )
        default = (
            param.default if param.default is not inspect.Parameter.empty else ...
        )
        fields[name] = (annotation, Field(default=default))

    if not fields:
        return None
    return create_model(f"{writer_tool.name}_args", **fields)  # type: ignore[return-value]


def to_langchain_tools(
    registry: "ToolRegistry", runtime: ToolRuntime
) -> list[BaseTool]:
    """Wrap every registered writer tool as a LangChain ``BaseTool``.

    The returned tools invoke the writer ``Tool.run(runtime, **kwargs)``
    contract and surface ``ToolResult.output`` to LangChain. Structured
    output (``truncated``, ``metadata``) is dropped at this seam — it's
    recorded by LangGraph state separately (per 04).
    """

    def _make(writer_tool: "Tool") -> BaseTool:
        def _invoke(**kwargs: object) -> str:
            return writer_tool.run(runtime, **kwargs).output

        # ``__name__`` matters for LangChain tool discovery, and ``__doc__``
        # becomes the tool description surfaced to the model.
        _invoke.__name__ = writer_tool.name
        _invoke.__doc__ = writer_tool.description

        args_schema = _build_args_schema(writer_tool)
        return StructuredTool.from_function(
            _invoke,
            name=writer_tool.name,
            description=writer_tool.description,
            args_schema=args_schema,
        )

    return [
        _make(registry.get(name)) for name in registry.names()
    ]


__all__ = ["to_langchain_tools"]
