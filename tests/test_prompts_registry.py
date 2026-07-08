"""Unit tests for :mod:`writer.prompts.registry`.

Covers:

* registration of the built-in prompts;
* :meth:`PromptRegistry.get` / :meth:`require` semantics (including
  the missing-key error path);
* :meth:`by_role` ordering (sorted by genre);
* duplicate-key rejection at construction time.
"""

from __future__ import annotations

import pytest

from writer.prompts.protocol import PromptBundle, PromptKey
from writer.prompts.registry import (
    BUILTIN_PROMPTS,
    PromptRegistry,
    PromptRegistryError,
    builtin_prompt_registry,
)


def test_builtin_registry_has_router_and_outline_keys() -> None:
    """The shipped registry must contain the router + four outline keys."""

    reg = builtin_prompt_registry()
    keys = {str(k) for k in reg.keys()}  # noqa: SIM118 — PromptRegistry is not a dict
    assert "router" in keys
    assert "outline" in keys
    assert "outline.历史" in keys
    assert "outline.言情" in keys
    assert "outline.玄幻" in keys


def test_registry_get_returns_correct_bundle() -> None:
    reg = builtin_prompt_registry()
    bundle = reg.get(PromptKey(role="outline", genre="历史"))
    assert bundle is not None
    assert bundle.key == PromptKey(role="outline", genre="历史")
    assert bundle.command == "/大纲"


def test_registry_get_returns_none_for_missing_key() -> None:
    reg = builtin_prompt_registry()
    assert reg.get(PromptKey(role="does_not_exist")) is None


def test_registry_require_raises_for_missing_key() -> None:
    reg = builtin_prompt_registry()
    with pytest.raises(PromptRegistryError, match="no prompt registered"):
        reg.require(PromptKey(role="nope"))


def test_by_role_returns_all_genre_variants_sorted() -> None:
    reg = builtin_prompt_registry()
    outlines = reg.by_role("outline")
    genres = [b.key.genre for b in outlines]
    # Sorted alphabetically by PromptKey string form
    assert genres == sorted(genres)
    assert set(genres) == {"other", "历史", "言情", "玄幻"}


def test_by_role_excludes_other_roles() -> None:
    reg = builtin_prompt_registry()
    routers = reg.by_role("router")
    assert len(routers) == 1
    assert routers[0].key.role == "router"


def test_duplicate_key_raises_at_construction() -> None:
    """Two bundles with the same key trigger a duplicate-key error."""

    duplicate = PromptBundle(
        key=PromptKey(role="router"),
        template=BUILTIN_PROMPTS[0].template,  # reuse so the registry accepts shape
        command=None,
    )
    with pytest.raises(PromptRegistryError, match="duplicate prompt key"):
        PromptRegistry(prompts=list(BUILTIN_PROMPTS), extra_prompts=[duplicate])


def test_extra_prompts_are_added_after_builtins() -> None:
    """Plugins can register new keys without colliding with built-ins."""

    from langchain_core.prompts import ChatPromptTemplate

    custom = PromptBundle(
        key=PromptKey(role="custom_outline"),
        template=ChatPromptTemplate.from_messages([("human", "{x}")]),
        command=None,
    )
    reg = PromptRegistry(prompts=list(BUILTIN_PROMPTS), extra_prompts=[custom])
    assert reg.get(PromptKey(role="custom_outline")) is custom


def test_invalid_bundle_key_raises() -> None:
    from langchain_core.prompts import ChatPromptTemplate

    bad = PromptBundle(
        key=PromptKey(role=""),  # empty role
        template=ChatPromptTemplate.from_messages([("human", "{x}")]),
        command=None,
    )
    with pytest.raises(PromptRegistryError, match="role must be"):
        PromptRegistry(prompts=[bad])


def test_prompt_key_string_form() -> None:
    """``str(PromptKey)`` is the canonical lookup string."""

    assert str(PromptKey(role="outline")) == "outline"
    assert str(PromptKey(role="outline", genre="历史")) == "outline.历史"


def test_keys_returns_sorted_strings() -> None:
    reg = builtin_prompt_registry()
    keys = [str(k) for k in reg.keys()]  # noqa: SIM118 — PromptRegistry is not a dict
    assert keys == sorted(keys)
