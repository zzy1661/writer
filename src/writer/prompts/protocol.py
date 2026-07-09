"""Prompt protocol — the metadata types used by :mod:`writer.prompts.registry`.

Centralizing prompts mirrors the design choice made by
:mod:`writer.skills.registry` and :mod:`writer.tools.registry`: a small
typed wrapper plus a registry that can be replaced or extended without
touching call sites.

A :class:`PromptBundle` is the unit of dispatch: it carries one
:class:`langchain_core.prompts.ChatPromptTemplate` plus the composite
key (:class:`PromptKey`) under which it is registered. The composite key
is shaped ``(role, genre)`` because the four genre Agents
(``HistoryAgent`` / ``XuanhuanAgent`` / ``RomanceAgent``
/ ``StoryAgent``) all consume the same ``outline`` role but with
different identities.

The dataclasses are ``frozen=True`` so callers cannot mutate a bundle
after registration — the only sanctioned way to swap a prompt is to
build a new registry. This matches the convention already in place for
:class:`writer.engine.events.Done` (also ``frozen=True``).
"""

from __future__ import annotations

from dataclasses import dataclass

from langchain_core.prompts import ChatPromptTemplate


@dataclass(frozen=True)
class PromptKey:
    """Composite lookup key — ``(role, genre)`` covers most call sites.

    ``role`` distinguishes the *kind* of LLM call:
    ``"router"`` / ``"outline"`` / ``"toc"`` / ``"init_brief"``.

    ``genre`` distinguishes the agent identity (and the
    genre-specific outline fallback): ``"历史"`` / ``"言情"`` /
    ``"玄幻"`` / ``"other"``. The default ``"other"`` is the catch-all
    used by :class:`writer.roles.StoryAgent` and by shared roles
    like ``"toc"`` and ``"init_brief"`` that do not branch by genre.
    """

    role: str
    genre: str = "other"

    def __str__(self) -> str:
        if self.genre == "other":
            return self.role
        return f"{self.role}.{self.genre}"


@dataclass(frozen=True)
class PromptBundle:
    """One LLM call's complete surface.

    ``key`` is the lookup handle; ``template`` is what call sites
    render before invoking the LLM; ``command`` is an optional hint
    used by tooling that wants to map a prompt back to a slash command
    (it is not used by the registry's lookup logic).
    """

    key: PromptKey
    template: ChatPromptTemplate
    command: str | None = None


__all__ = ["PromptBundle", "PromptKey"]
