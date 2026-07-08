"""Prompt registry — maps :class:`PromptKey` to :class:`PromptBundle`.

This module mirrors the design of
:mod:`writer.skills.registry.SkillRegistry` and
:mod:`writer.tools.registry.built_tool_registry`:

* :class:`PromptRegistry` is a thin lookup table keyed by
  :class:`PromptKey`. Built-in prompts are passed in via ``prompts=``;
  third-party plugins are loaded via :func:`discover_entry_point_prompts`
  and merged via ``extra_prompts=``. Built-ins win on key collision —
  a plugin that shadows a core prompt triggers a duplicate-key error
  rather than silently overwriting.
* :func:`builtin_prompt_registry` returns the built-in prompts only.
  The ``JSON_CONTRACT_TEMPLATE``-style deepseek fallback is intentionally
  *not* registered here because it depends on a runtime Pydantic schema
  supplied per call; callers should compose it from
  :func:`writer.prompts.shared.json_contract_message` at call time.
* :func:`discover_entry_point_prompts` reads
  ``[project.entry-points."writer.prompts"]`` so third-party plugins can
  ship extra prompts without forking the registry.

The :exc:`PromptRegistryError` exception type parallels
:exc:`writer.skills.errors.SkillError` so both registries fail loudly
on configuration mistakes.
"""

from __future__ import annotations

import logging
from importlib import metadata
from typing import TYPE_CHECKING

from writer.prompts.consultants import (
    INIT_BRIEF_TEMPLATE,
    OUTLINE_TEMPLATE_HISTORY,
    OUTLINE_TEMPLATE_ROMANCE,
    OUTLINE_TEMPLATE_STORY,
    OUTLINE_TEMPLATE_XUANHUAN,
    TOC_TEMPLATE,
)
from writer.prompts.protocol import PromptBundle, PromptKey
from writer.prompts.router import COMMAND_AGENT_TEMPLATE

if TYPE_CHECKING:
    from pydantic import BaseModel

log = logging.getLogger(__name__)


ENTRY_POINT_GROUP = "writer.prompts"


class PromptRegistryError(ValueError):
    """Raised when a prompt registration is invalid (bad key, duplicate)."""


# Built-in prompts shipped with the agent. Order matters only for the
# fall-through default-arg case in :class:`PromptRegistry` — later
# registrations win on key collision, mirroring the skills registry
# behaviour. Built-ins come first in :func:`built_prompt_registry` so
# a plugin shadowing a core key triggers the duplicate-key error.
BUILTIN_PROMPTS: list[PromptBundle] = [
    PromptBundle(
        key=PromptKey(role="router"),
        template=COMMAND_AGENT_TEMPLATE,
        command=None,
    ),
    PromptBundle(
        key=PromptKey(role="outline", genre="other"),
        template=OUTLINE_TEMPLATE_STORY,
        command="/大纲",
    ),
    PromptBundle(
        key=PromptKey(role="outline", genre="历史"),
        template=OUTLINE_TEMPLATE_HISTORY,
        command="/大纲",
    ),
    PromptBundle(
        key=PromptKey(role="outline", genre="言情"),
        template=OUTLINE_TEMPLATE_ROMANCE,
        command="/大纲",
    ),
    PromptBundle(
        key=PromptKey(role="outline", genre="玄幻"),
        template=OUTLINE_TEMPLATE_XUANHUAN,
        command="/大纲",
    ),
    PromptBundle(
        key=PromptKey(role="toc"),
        template=TOC_TEMPLATE,
        command="/目录",
    ),
    PromptBundle(
        key=PromptKey(role="init_brief"),
        template=INIT_BRIEF_TEMPLATE,
        command="/init",
    ),
]


class PromptRegistry:
    """Lookup table for :class:`PromptBundle`.

    Duplicate keys raise :class:`PromptRegistryError` at construction
    time. The first registration wins (built-ins are added before entry
    points via :func:`built_prompt_registry`).
    """

    def __init__(
        self,
        prompts: list[PromptBundle] | None = None,
        *,
        extra_prompts: list[PromptBundle] | None = None,
    ) -> None:
        items: list[PromptBundle] = list(prompts) if prompts is not None else list(BUILTIN_PROMPTS)
        if extra_prompts:
            items.extend(extra_prompts)

        seen: dict[PromptKey, PromptBundle] = {}
        for bundle in items:
            self._validate_bundle(bundle)
            if bundle.key in seen:
                msg = (
                    f"duplicate prompt key {bundle.key!s}: "
                    f"{seen[bundle.key].template!r} vs {bundle.template!r}"
                )
                raise PromptRegistryError(msg)
            seen[bundle.key] = bundle

        self._by_key: dict[PromptKey, PromptBundle] = seen

    # ----- introspection ----------------------------------------------------

    def get(self, key: PromptKey) -> PromptBundle | None:
        return self._by_key.get(key)

    def require(self, key: PromptKey) -> PromptBundle:
        """Return the bundle for ``key`` or raise :class:`PromptRegistryError`.

        Mirrors the style of :meth:`writer.skills.registry.SkillRegistry.run`:
        missing keys surface as a clear error rather than ``None``.
        """

        bundle = self._by_key.get(key)
        if bundle is None:
            msg = f"no prompt registered for key {key!s}"
            raise PromptRegistryError(msg)
        return bundle

    def by_role(self, role: str) -> list[PromptBundle]:
        """Return all bundles whose key has ``role=role``, sorted by genre."""

        return sorted(
            (bundle for bundle in self._by_key.values() if bundle.key.role == role),
            key=lambda bundle: bundle.key.genre,
        )

    def by_schema(self, schema: type[BaseModel]) -> list[PromptBundle]:
        """Return all bundles whose template declares ``schema`` in its variables.

        This is a *hint* surface for tooling that wants to map a Pydantic
        model back to the prompts that produce it (e.g. for documentation
        or for static sanity-checks in tests). It walks the template's
        declared input variables and matches on equality.
        """

        target_name = schema.__name__
        return [
            bundle
            for bundle in self._by_key.values()
            if any(
                var_name == target_name
                for var_name in (
                    bundle.template.input_variables
                    if hasattr(bundle.template, "input_variables")
                    else ()
                )
            )
        ]

    def keys(self) -> list[PromptKey]:
        """Return all registered keys sorted by their string form."""

        return sorted(self._by_key, key=str)

    # ----- validation -------------------------------------------------------

    @staticmethod
    def _validate_bundle(bundle: PromptBundle) -> None:
        if not isinstance(bundle.key, PromptKey):
            msg = f"bundle key must be PromptKey, got {type(bundle.key).__name__}"
            raise PromptRegistryError(msg)
        if not bundle.key.role:
            msg = "bundle key.role must be a non-empty string"
            raise PromptRegistryError(msg)
        if not bundle.key.genre:
            msg = "bundle key.genre must be a non-empty string"
            raise PromptRegistryError(msg)
        if bundle.template is None:  # pragma: no cover — defensive
            msg = f"bundle {bundle.key!s} has no template"
            raise PromptRegistryError(msg)


def discover_entry_point_prompts() -> list[PromptBundle]:
    """Discover prompts registered as ``[project.entry-points."writer.prompts"]``.

    Each entry point may resolve to either:

    * a :class:`PromptBundle` class — instantiated with no arguments;
    * a pre-built :class:`PromptBundle` instance — used as-is.

    Anything that fails to resolve (missing distribution, ImportError,
    bad attribute, unexpected type, :exc:`PromptRegistryError` from the
    validators) is logged at WARNING and skipped — a broken plugin
    never blocks startup.
    """

    discovered: list[PromptBundle] = []
    try:
        entries = metadata.entry_points(group=ENTRY_POINT_GROUP)
    except Exception:  # noqa: BLE001 — entry-points API can raise in odd envs
        log.warning("Prompt entry_points discovery failed; continuing without plugins")
        return discovered

    for entry in entries:
        try:
            target = entry.load()
        except Exception:  # noqa: BLE001 — misbehaving plugins must not crash startup
            log.warning(
                "Failed to import prompt entry point %s=%s; skipping",
                entry.name,
                entry.value,
            )
            continue

        try:
            if isinstance(target, type):
                instance: PromptBundle = target()  # type: ignore[abstract]
            elif isinstance(target, PromptBundle):
                instance = target
            else:
                log.warning(
                    "Prompt entry point %s did not resolve to a PromptBundle "
                    "(got %s); skipping",
                    entry.name,
                    type(target).__name__,
                )
                continue
        except Exception:  # noqa: BLE001 — constructor failures must not crash startup
            log.warning(
                "Prompt entry point %s constructor raised; skipping",
                entry.name,
            )
            continue

        try:
            PromptRegistry._validate_bundle(instance)
        except PromptRegistryError as exc:
            log.warning("Prompt entry point %s rejected: %s", entry.name, exc)
            continue

        discovered.append(instance)
    return discovered


def builtin_prompt_registry() -> PromptRegistry:
    """Built-in prompts only — no entry-point plugins.

    Used as the default by :class:`writer.roles.StoryConsultant` when
    the caller does not inject a custom registry. Tests that need a
    pristine registry (no plugins) should call this rather than
    :func:`built_prompt_registry`.
    """

    return PromptRegistry()


def built_prompt_registry() -> PromptRegistry:
    """Built-in prompts + entry-point plugins; built-ins win on key collision.

    Mirrors :func:`writer.skills.registry.built_skill_registry`. Built-ins
    are listed first so a plugin shadowing ``outline.历史`` triggers the
    duplicate-key error in :class:`PromptRegistry.__init__` — silently
    letting a plugin clobber a core prompt would make behaviour
    non-deterministic and hard to debug.
    """

    extras = discover_entry_point_prompts()
    if not extras:
        return PromptRegistry()
    return PromptRegistry(prompts=list(BUILTIN_PROMPTS), extra_prompts=extras)


__all__ = [
    "BUILTIN_PROMPTS",
    "ENTRY_POINT_GROUP",
    "PromptRegistry",
    "PromptRegistryError",
    "built_prompt_registry",
    "builtin_prompt_registry",
    "discover_entry_point_prompts",
]
