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
