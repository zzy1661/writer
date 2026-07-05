"""Tests for EngineDeps wiring (router selection, tool registry, runtime)."""

from __future__ import annotations

from pathlib import Path

from pydantic import SecretStr

from writer.config import Settings
from writer.engine.deps import production_deps
from writer.routing import CompositeRouter, LlmIntentRouter, RuleBasedIntentRouter
from writer.tools import ToolRegistry, ToolRuntime


def _settings(*, with_key: bool) -> Settings:
    return Settings(
        model="gpt-4o-mini",
        api_key=SecretStr("sk-test") if with_key else None,
        base_url="https://api.openai.com/v1",
        temperature=0.0,
    )


def test_production_deps_uses_llm_router_when_api_key_set() -> None:
    deps = production_deps(_settings(with_key=True))

    assert isinstance(deps.router, CompositeRouter)
    assert isinstance(deps.router.primary, RuleBasedIntentRouter)
    assert isinstance(deps.router.fallback, LlmIntentRouter)


def test_production_deps_uses_rule_router_when_no_api_key() -> None:
    deps = production_deps(_settings(with_key=False))

    # Bare rule router, NOT wrapped in CompositeRouter
    assert type(deps.router) is RuleBasedIntentRouter


def test_production_deps_exposes_tool_registry() -> None:
    deps = production_deps(_settings(with_key=False))

    assert isinstance(deps.tool_registry, ToolRegistry)
    # built_tool_registry() registers at least these tools
    assert "foreshadow_query" in deps.tool_registry
    assert "chapter_locate" in deps.tool_registry
    assert "safe_read_file" in deps.tool_registry


def test_production_deps_exposes_tool_runtime() -> None:
    deps = production_deps(_settings(with_key=False))

    assert isinstance(deps.tool_runtime, ToolRuntime)


def test_production_deps_uses_sentinel_runtime_when_no_project_root() -> None:
    deps = production_deps(_settings(with_key=False))

    # Sentinel keeps tool runtime alive in S0; runtime is callable
    assert deps.tool_runtime.project_root == Path("/__no_project__").resolve()


def test_production_deps_respects_explicit_project_root(tmp_path: Path) -> None:
    deps = production_deps(_settings(with_key=False), project_root=tmp_path)

    assert deps.tool_runtime.project_root == tmp_path.resolve()


def test_built_tool_registry_is_usable_via_deps() -> None:
    """Spot-check: the deps-wired registry can actually dispatch a tool call."""
    deps = production_deps(_settings(with_key=False))

    # chapter_locate is path-free; safe to call with S0 runtime
    result = deps.tool_registry.invoke(
        "chapter_locate", deps.tool_runtime, chapter="1.1"
    )
    assert result.output
    assert "chapter_id" in result.metadata


# ---------------------------------------------------------------------------
# primary_router kwarg (arch-optimizer N3, 2026-07-05)
# ---------------------------------------------------------------------------


def test_production_deps_respects_explicit_primary_router_when_no_api_key() -> None:
    """When ``primary_router`` is passed, production_deps uses it as the bare router.

    Per arch-optimizer N3 (2026-07-05): before M5, ``production_deps``
    hard-coded ``RuleBasedIntentRouter()`` inside the factory. M5 added
    the ``primary_router`` kwarg so tests / callers can inject a custom
    rule router without rewriting ``_select_router``. This test covers
    the no-api-key path: the bare router IS the supplied sentinel.
    """
    sentinel = RuleBasedIntentRouter()

    deps = production_deps(_settings(with_key=False), primary_router=sentinel)

    # No API key → bare rule router, NOT wrapped in CompositeRouter
    assert deps.router is sentinel


def test_production_deps_respects_explicit_primary_router_with_api_key() -> None:
    """When ``primary_router`` is passed AND an API key is set, the sentinel becomes CompositeRouter.primary.

    Companion to the no-api-key test. With API key configured,
    ``production_deps`` wraps the primary in a :class:`CompositeRouter`
    (rule-first, LLM fallback). The sentinel must be wired as the
    primary, not silently replaced by a fresh ``RuleBasedIntentRouter``.
    """
    sentinel = RuleBasedIntentRouter()

    deps = production_deps(_settings(with_key=True), primary_router=sentinel)

    assert isinstance(deps.router, CompositeRouter)
    assert deps.router.primary is sentinel
    # Fallback is the LLM router; primary must remain the sentinel
    assert isinstance(deps.router.fallback, LlmIntentRouter)
