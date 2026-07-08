"""Unit tests for :mod:`writer.prompts.registry.discover_entry_point_prompts`.

The entry-points API can raise in odd environments (older Python,
malformed ``pyproject.toml``, missing distributions). The discover
function must:

* return an empty list rather than crashing when entry-point lookup
  fails outright;
* skip non-``PromptBundle`` entry points with a warning rather than
  raising.

We exercise the failure paths by patching :func:`importlib.metadata.entry_points`.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from writer.prompts.protocol import PromptBundle, PromptKey
from writer.prompts.registry import (
    ENTRY_POINT_GROUP,
    PromptRegistry,
    discover_entry_point_prompts,
)
from writer.prompts.shared import json_contract_message


class _RaisingEntryPoints:
    """Stand-in for ``importlib.metadata.entry_points`` that raises."""

    def __init__(self, group: str) -> None:
        del group
        msg = "metadata backend unavailable"
        raise RuntimeError(msg)


class _FakeEntryPoints:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def __call__(self, group: str | None = None) -> Any:
        del group
        return _FakeIter(self._items)


class _FakeIter:
    def __init__(self, items: list[Any]) -> None:
        self._items = items

    def __iter__(self) -> _FakeIter:
        return self

    def __next__(self) -> Any:
        if not self._items:
            raise StopIteration
        return self._items.pop(0)


class _FakeEntry:
    def __init__(self, name: str, value: str, payload: Any) -> None:
        self.name = name
        self.value = value
        self._payload = payload

    def load(self) -> Any:
        return self._payload


class _NotAPromptBundle:
    """A class that resolves to something other than ``PromptBundle``."""

    pass


def test_discover_returns_empty_on_metadata_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(
        "writer.prompts.registry.metadata.entry_points",
        _RaisingEntryPoints,
    )
    with caplog.at_level(logging.WARNING, logger="writer.prompts.registry"):
        result = discover_entry_point_prompts()

    assert result == []
    assert any("entry_points discovery failed" in rec.message for rec in caplog.records)


def test_discover_skips_non_prompt_bundle_entry_points(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    entries = [_FakeEntry("bad", "pkg.mod:Cls", _NotAPromptBundle())]
    monkeypatch.setattr(
        "writer.prompts.registry.metadata.entry_points",
        _FakeEntryPoints(entries),
    )

    with caplog.at_level(logging.WARNING, logger="writer.prompts.registry"):
        result = discover_entry_point_prompts()

    assert result == []
    assert any("did not resolve to a PromptBundle" in rec.message for rec in caplog.records)


def test_discover_skips_failing_loads(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _BoomEntry:
        name = "boom"
        value = "pkg.mod:Cls"

        def load(self) -> Any:
            raise ImportError("nope")

    entries = [_BoomEntry()]  # type: ignore[list-item]
    monkeypatch.setattr(
        "writer.prompts.registry.metadata.entry_points",
        _FakeEntryPoints(entries),
    )

    with caplog.at_level(logging.WARNING, logger="writer.prompts.registry"):
        result = discover_entry_point_prompts()

    assert result == []
    assert any("Failed to import prompt entry point" in rec.message for rec in caplog.records)


def test_discover_accepts_prompt_bundle_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pre-built :class:`PromptBundle` instance is accepted as-is."""

    from langchain_core.prompts import ChatPromptTemplate

    bundle = PromptBundle(
        key=PromptKey(role="custom"),
        template=ChatPromptTemplate.from_messages([("human", "{x}")]),
        command=None,
    )
    entries = [_FakeEntry("custom", "pkg.mod:bundle", bundle)]
    monkeypatch.setattr(
        "writer.prompts.registry.metadata.entry_points",
        _FakeEntryPoints(entries),
    )

    result = discover_entry_point_prompts()

    assert len(result) == 1
    assert result[0] is bundle


def test_entry_point_group_is_writer_prompts() -> None:
    assert ENTRY_POINT_GROUP == "writer.prompts"


# A smoke test that ensures ``json_contract_message`` (used by the
# JSON-prompt structured-output fallback) still imports and produces a
# SystemMessage.
def test_json_contract_message_imports_cleanly() -> None:
    from pydantic import BaseModel

    class _M(BaseModel):
        x: int

    msg = json_contract_message(_M)
    assert "JSON" in msg.content
    assert "_M" in msg.content or '"x"' in msg.content


def test_json_contract_message_uses_prompts_shared() -> None:
    """The structured helper must delegate to writer.prompts.shared."""

    from writer.llm import structured as llm_structured

    # The internal helper should be the prompts.shared implementation
    from writer.prompts.shared import json_contract_message as prompt_helper

    assert llm_structured._json_contract_message is prompt_helper


def test_duplicate_key_in_registry_via_construct() -> None:
    """Two built-ins with the same key trigger a duplicate-key error."""

    from langchain_core.prompts import ChatPromptTemplate

    template = ChatPromptTemplate.from_messages([("human", "{x}")])
    a = PromptBundle(key=PromptKey(role="dup"), template=template, command=None)
    b = PromptBundle(key=PromptKey(role="dup"), template=template, command=None)

    with pytest.raises(Exception, match="duplicate"):
        PromptRegistry(prompts=[a, b])
