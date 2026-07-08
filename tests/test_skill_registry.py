"""Tests for the enhanced ``SkillRegistry`` and the Skill metadata contract.

Coverage:
* duplicate-command detection
* ``help_entries()`` ordering and stability
* ``state_matrix()`` derivation from ``requires_states``
* ``commands()`` sort order
* validation of metadata (missing / wrong-type fields raise ``SkillError``)
* ``Skill.run`` for an unknown command raises ``SkillError``
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from writer.project import ProjectState
from writer.skills import (
    BUILTIN_SKILLS,
    ContinueWritingSkill,
    OutlineSkill,
    ReviseSkill,
    Skill,
    SkillError,
    SkillRegistry,
    TocSkill,
    built_skill_registry,
)
from writer.skills.protocol import Skill as SkillProtocol

if TYPE_CHECKING:
    from collections.abc import AsyncIterator

    from writer.engine import Done, TextChunk
    from writer.engine.config import EngineConfig
    from writer.engine.context import EngineContext
    from writer.engine.deps import EngineDeps


# ---------------------------------------------------------------------------
# built_skill_registry / BUILTIN_SKILLS
# ---------------------------------------------------------------------------


def test_builtin_skills_contains_expected_skills() -> None:
    """built_skill_registry must register the four built-in Skills by name."""

    names = {type(skill).__name__ for skill in BUILTIN_SKILLS}
    assert names == {"OutlineSkill", "TocSkill", "ContinueWritingSkill", "ReviseSkill"}


def test_built_skill_registry_registers_outline_toc_continue_revise() -> None:
    registry = built_skill_registry()

    outline = registry.get("/大纲")
    toc = registry.get("/目录")
    cont = registry.get("/续写")
    rev = registry.get("/改")
    assert isinstance(outline, OutlineSkill)
    assert isinstance(toc, TocSkill)
    assert isinstance(cont, ContinueWritingSkill)
    assert isinstance(rev, ReviseSkill)


def test_built_skill_registry_commands_are_sorted() -> None:
    """``commands()`` must return sorted slash commands for deterministic completion."""

    registry = built_skill_registry()

    assert registry.commands() == sorted(registry.commands())
    assert registry.commands() == ["/大纲", "/改", "/目录", "/续写"]


def test_built_skill_registry_help_entries_keys_match_commands() -> None:
    registry = built_skill_registry()

    help_commands = [cmd for cmd, _ in registry.help_entries()]
    assert help_commands == registry.commands()


# ---------------------------------------------------------------------------
# Metadata validation
# ---------------------------------------------------------------------------


def test_skill_registry_rejects_skill_missing_command() -> None:
    class _Broken(Skill):
        command = "大纲"  # missing leading "/"

        async def run(
            self,
            ctx: EngineContext,
            deps: EngineDeps,
            cfg: EngineConfig,
        ) -> AsyncIterator[TextChunk | Done]:
            return
            yield  # unreachable but satisfies the protocol shape

    with pytest.raises(SkillError, match="command"):
        SkillRegistry([_Broken()])  # type: ignore[arg-type]


def test_skill_registry_rejects_skill_with_blank_description() -> None:
    class _NoDescription(OutlineSkill):
        description = "   "

    with pytest.raises(SkillError, match="description"):
        SkillRegistry([_NoDescription()])


def test_skill_registry_rejects_skill_with_non_frozenset_requires_states() -> None:
    class _MutableStates(OutlineSkill):
        requires_states = {ProjectState.INITIALIZED}  # type: ignore[assignment]

    with pytest.raises(SkillError, match="requires_states"):
        SkillRegistry([_MutableStates()])


def test_skill_registry_rejects_skill_with_empty_requires_states() -> None:
    class _EmptyStates(OutlineSkill):
        requires_states = frozenset()  # type: ignore[assignment]

    with pytest.raises(SkillError, match="requires_states"):
        SkillRegistry([_EmptyStates()])


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------


def test_skill_registry_later_wins_over_earlier() -> None:
    """Same ``command`` appearing twice → later entry replaces earlier.

    Per ``chg-project-skills`` Decision 8: Replace semantics let the
    project-level layer override the built-in layer (and the entry-point
    layer override both) without raising.
    """

    class _CustomOutline(OutlineSkill):
        description = "project-level override"

    registry = SkillRegistry([OutlineSkill(), _CustomOutline()])
    assert isinstance(registry.get("/大纲"), _CustomOutline)


def test_skill_registry_extras_override_skills() -> None:
    """``extra_skills`` are appended after ``skills`` and win on collision.

    Combined with the test above, this is the canonical "project skill
    replaces built-in" path: built_skill_registry feeds ``BUILTIN_SKILLS``
    as ``skills`` and project skills as ``extra_skills``; the project
    skill must replace the built-in by command.
    """

    class _ProjectOutline(OutlineSkill):
        description = "from project skills"

    registry = SkillRegistry(
        skills=[OutlineSkill(), TocSkill()],
        extra_skills=[_ProjectOutline()],
    )
    assert isinstance(registry.get("/大纲"), _ProjectOutline)
    assert isinstance(registry.get("/目录"), TocSkill)


def test_skill_registry_allows_extras_to_come_after_builtins() -> None:
    """``extra_skills`` extend (not replace) ``skills``; both layers coexist."""

    extras = [ContinueWritingSkill()]
    registry = SkillRegistry(skills=[OutlineSkill(), TocSkill()], extra_skills=extras)

    assert isinstance(registry.get("/大纲"), OutlineSkill)
    assert isinstance(registry.get("/目录"), TocSkill)
    assert isinstance(registry.get("/续写"), ContinueWritingSkill)


# ---------------------------------------------------------------------------
# state_matrix() / help_entries() correctness
# ---------------------------------------------------------------------------


def test_state_matrix_matches_each_skill_requires_states() -> None:
    registry = built_skill_registry()

    matrix = registry.state_matrix()
    assert matrix["/大纲"] == OutlineSkill().requires_states
    assert matrix["/目录"] == TocSkill().requires_states
    assert matrix["/续写"] == ContinueWritingSkill().requires_states
    assert matrix["/改"] == ReviseSkill().requires_states


def test_state_matrix_excludes_modified_requires_states() -> None:
    """Custom Skill subclasses surface their own requires_states."""

    class _TocOnlyAtS4(TocSkill):
        requires_states = frozenset({ProjectState.WRITING})

    registry = SkillRegistry([_TocOnlyAtS4()])
    assert registry.state_matrix()["/目录"] == frozenset({ProjectState.WRITING})


def test_help_entries_returns_command_description_tuples() -> None:
    registry = built_skill_registry()

    pairs = registry.help_entries()
    assert ("/大纲", OutlineSkill().description) in pairs
    assert ("/目录", TocSkill().description) in pairs
    assert ("/续写", ContinueWritingSkill().description) in pairs
    assert ("/改", ReviseSkill().description) in pairs


# ---------------------------------------------------------------------------
# get() and run() semantic
# ---------------------------------------------------------------------------


def test_get_returns_none_for_unknown_command() -> None:
    registry = built_skill_registry()

    assert registry.get("/not-a-real-skill") is None
    assert registry.get("大纲") is None  # missing leading "/" — never matches


def test_run_raises_skill_error_for_unknown_command(tmp_path: Path) -> None:
    """``run()`` is the legacy entrypoint; it must raise ``SkillError`` consistently
    with the new ``KeyError`` contract users expect when the command isn't
    registered (per arch-optimizer — keep the error type in the SkillError family)."""

    import asyncio

    from writer.engine.config import build_engine_config
    from writer.engine.context import EngineContext
    from writer.engine.deps import production_deps

    registry = built_skill_registry()
    ctx = EngineContext(
        user_input="/nonexistent",
        project_root=tmp_path,
        project_state="S0",
        session_id="t",
    )
    deps = production_deps(project_root=tmp_path)

    async def drain() -> None:
        async for _ in registry.run("/nonexistent", ctx, deps, build_engine_config(ctx)):
            pass

    with pytest.raises(SkillError, match="未注册 skill"):
        asyncio.run(drain())


# ---------------------------------------------------------------------------
# Skill Protocol is runtime-checkable (preserve prior contract)
# ---------------------------------------------------------------------------


def test_skill_protocol_is_runtime_checkable() -> None:
    """The Skill Protocol keeps its @runtime_checkable behaviour so callers
    can ask ``isinstance(skill, Skill)`` — this was the original contract and
    must not regress when we add metadata fields."""

    registry = built_skill_registry()
    outline = registry.get("/大纲")
    assert outline is not None
    assert isinstance(outline, SkillProtocol)
