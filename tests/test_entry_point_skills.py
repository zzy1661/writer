"""Tests for ``discover_entry_point_skills`` and the plugin-registration
contract documented in :mod:`writer.skills.registry`.

We don't ship third-party plugins as part of the project test suite, so
the strategy is to monkeypatch ``importlib.metadata.entry_points`` and
exercise every branch (class load, instance load, attribute error,
non-Skill return value, validator rejection) against in-test fake
modules.
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

from writer.engine.events import Done, TextChunk
from writer.skills.registry import (
    ENTRY_POINT_GROUP,
    built_skill_registry,
    discover_entry_point_skills,
)
from writer.skills.toc import TocSkill

if TYPE_CHECKING:
    from writer.engine.config import EngineConfig
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps


# A pre-built skill instance that the tests hand to a fake entry-point.
class _AlreadyBuiltSkill:
    """Pre-constructed instance — entry-point discovery should pass it through.

    ``@runtime_checkable`` Skill requires a ``run`` method to recognise
    subclasses as structurally valid, so even "pre-built" test doubles
    must declare the method (with a body that never executes —
    discovery doesn't actually invoke it)."""

    command = "/ep_instance"
    description = "entry-point: pre-built instance"
    requires_states = frozenset({"S1"})  # type: ignore[arg-type]
    extra_instructions = ""

    async def run(
        self,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        yield TextChunk(text="")

        del ctx
        del deps
        del cfg


# A skill class that requires zero args — entry-point discovery should `cls()` it.
class _ClassSkill:
    command = "/ep_class"
    description = "entry-point: class to instantiate"
    requires_states = frozenset({"S1"})  # type: ignore[arg-type]
    extra_instructions = ""

    async def run(
        self,
        ctx: EngineContext,
        deps: EngineDeps,
        cfg: EngineConfig,
    ) -> AsyncIterator[TextChunk | Done]:
        yield TextChunk(text="")

        del ctx
        del deps
        del cfg


class _BadMetadataSkill(TocSkill):
    description = ""  # invalid → registry validator should reject


def _fake_entry_points(*entries: tuple[str, object, str]):
    """Build an iterable of fake entry-point objects usable by the discovery loop.

    Each entry is ``(name, value_string, load_return)`` where
    ``load_return`` is what ``entry.load()`` should produce.
    """

    out = []
    for name, value, load_return in entries:
        ep = MagicMock()
        ep.name = name
        ep.value = value
        ep.load.return_value = load_return
        out.append(ep)
    return out


def test_discover_returns_empty_when_group_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    """No entry points → empty list (no warnings, no errors)."""

    def fake_entry_points(*, group: str) -> list[object]:
        return []

    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        fake_entry_points,
    )

    assert discover_entry_point_skills() == []


def test_discover_handles_skill_classes(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_eps = _fake_entry_points(
        ("my_plugin", "my_pkg.my_mod:MySkill", _ClassSkill),
    )

    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: fake_eps if group == ENTRY_POINT_GROUP else [],
    )

    discovered = discover_entry_point_skills()
    assert len(discovered) == 1
    assert isinstance(discovered[0], _ClassSkill)
    assert discovered[0].command == "/ep_class"


def test_discover_handles_skill_instances(monkeypatch: pytest.MonkeyPatch) -> None:
    prebuilt = _AlreadyBuiltSkill()
    fake_eps = _fake_entry_points(
        ("my_plugin", "my_pkg.my_mod:my_skill", prebuilt),
    )

    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: fake_eps if group == ENTRY_POINT_GROUP else [],
    )

    discovered = discover_entry_point_skills()
    assert discovered == [prebuilt]


def test_discover_skips_entry_point_with_import_error(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A broken plugin logs a WARNING and is skipped — startup must not crash."""

    bad_ep = MagicMock()
    bad_ep.name = "broken_plugin"
    bad_ep.value = "my_pkg.broken:Skill"
    bad_ep.load.side_effect = ImportError("simulated import failure")

    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: [bad_ep] if group == ENTRY_POINT_GROUP else [],
    )

    with caplog.at_level(logging.WARNING):
        result = discover_entry_point_skills()

    assert result == []
    assert any("broken_plugin" in record.message for record in caplog.records)


def test_discover_skips_entry_point_returning_non_skill(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """An entry point that resolves to a plain dict is silently skipped."""

    fake_eps = _fake_entry_points(
        ("weird_plugin", "weird_pkg.mod:confused", {"not": "a skill"}),
    )
    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: fake_eps if group == ENTRY_POINT_GROUP else [],
    )

    with caplog.at_level(logging.WARNING):
        result = discover_entry_point_skills()

    assert result == []
    assert any(
        "did not resolve to a Skill" in record.message for record in caplog.records
    )


def test_discover_skips_entry_point_rejected_by_validator(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A Skill with empty ``description`` fails the registry's validator."""

    fake_eps = _fake_entry_points(
        ("bad_meta", "pkg.mod:Bad", _BadMetadataSkill()),
    )
    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: fake_eps if group == ENTRY_POINT_GROUP else [],
    )

    with caplog.at_level(logging.WARNING):
        result = discover_entry_point_skills()

    assert result == []
    assert any("rejected" in record.message for record in caplog.records)


def test_discover_swallows_metadata_lookup_failure(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """``importlib.metadata.entry_points`` can raise in odd environments —
    discovery must swallow the failure so the REPL still starts."""

    def boom(**_: object) -> object:
        msg = "pkg_resources broken"
        raise RuntimeError(msg)

    monkeypatch.setattr("writer.skills.registry.metadata.entry_points", boom)

    with caplog.at_level(logging.WARNING):
        result = discover_entry_point_skills()

    assert result == []
    assert any("discovery failed" in record.message for record in caplog.records)


def test_built_skill_registry_includes_entry_point_discoveries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """End-to-end: ``built_skill_registry()`` picks up plugins."""

    fake_eps = _fake_entry_points(
        ("plugin_class", "p.mod:Skill", _ClassSkill),
        ("plugin_instance", "p.mod:inst", _AlreadyBuiltSkill()),
    )
    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: fake_eps if group == ENTRY_POINT_GROUP else [],
    )

    registry = built_skill_registry()

    # Built-ins still present
    assert registry.get("/大纲") is not None
    # Plugins registered
    assert isinstance(registry.get("/ep_class"), _ClassSkill)
    assert registry.get("/ep_instance") is not None


def test_built_skill_registry_later_wins_on_collision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A plugin shadowing ``/大纲`` REPLACES the built-in (last-write-wins).

    Per ``chg-project-skills`` Decision 8: the registry uses Replace
    semantics so the project-level layer can override the built-in
    layer and the entry-point layer can override both. This test
    pins the third (entry-point) layer.
    """

    class _ShadowOutline(TocSkill):
        command = "/大纲"
        description = "shadow outline"
        requires_states = frozenset({"S5"})  # type: ignore[arg-type]
        extra_instructions = ""

    fake_eps = _fake_entry_points(
        ("shadow", "p.mod:Skill", _ShadowOutline()),
    )
    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: fake_eps if group == ENTRY_POINT_GROUP else [],
    )

    registry = built_skill_registry()
    # Plugin wins, not built-in
    assert isinstance(registry.get("/大纲"), _ShadowOutline)
