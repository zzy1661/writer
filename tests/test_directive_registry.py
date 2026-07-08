"""Tests for the directive registry (chg-markdown-skills).

Replaces the prior ``test_skill_registry.py`` for the new
:class:`writer.skills.DirectiveRegistry` type. The public surface
(``get`` / ``commands`` / ``help_entries`` / ``state_matrix``) is
shape-compatible with the prior ``SkillRegistry`` so the broader CLI
REPL integration is unaffected.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from writer.skills import (
    DirectiveRegistry,
    SkillDirective,
    built_directive_registry,
)
from writer.project import ProjectState


def _directive(
    command: str = "/test",
    description: str = "test",
    requires=None,
) -> SkillDirective:
    if requires is None:
        requires_states = frozenset({ProjectState.INITIALIZED})
    else:
        # Bypass the default — ``requires or default`` would mask an
        # explicitly empty frozenset because empty frozenset is falsy.
        requires_states = requires
    return SkillDirective(
        command=command,
        description=description,
        requires_states=requires_states,
        body="body",
        references={},
        scripts=[],
        root=Path("/tmp/dummy"),
    )


# ---------------------------------------------------------------------------
# built_directive_registry (composes layers)
# ---------------------------------------------------------------------------


def test_built_directive_registry_no_project_root_returns_shipped() -> None:
    registry = built_directive_registry(project_root=None)
    commands = set(registry.commands())
    assert commands == {"/大纲", "/目录", "/续写", "/改"}


def test_built_directive_registry_shipped_have_descriptions() -> None:
    registry = built_directive_registry(project_root=None)
    for cmd in registry.commands():
        directive = registry.get(cmd)
        assert directive is not None
        assert directive.description, f"shipped {cmd} must have a description"


def test_built_directive_registry_project_shadows_shipped(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".writer" / "skills"
    skills_dir.mkdir(parents=True)
    project_skill = skills_dir / "大纲"
    project_skill.mkdir()
    (project_skill / "SKILL.md").write_text(
        "---\ncommand: /大纲\ndescription: project-level override\nrequires_states: [S1]\n---\nbody\n",
        encoding="utf-8",
    )

    registry = built_directive_registry(project_root=tmp_path)
    d = registry.get("/大纲")
    assert d is not None
    assert d.description == "project-level override"


def test_built_directive_registry_preserves_order_by_command() -> None:
    registry = built_directive_registry(project_root=None)
    assert registry.commands() == sorted(registry.commands())


# ---------------------------------------------------------------------------
# DirectiveRegistry.introspection
# ---------------------------------------------------------------------------


def test_registry_get_returns_none_for_unknown_command() -> None:
    registry = DirectiveRegistry(directives=[_directive(command="/x")])
    assert registry.get("/unknown") is None


def test_registry_commands_sorted() -> None:
    registry = DirectiveRegistry(
        directives=[
            _directive(command="/z"),
            _directive(command="/a"),
            _directive(command="/m"),
        ]
    )
    assert registry.commands() == ["/a", "/m", "/z"]


def test_registry_help_entries_pairs_command_with_description() -> None:
    registry = DirectiveRegistry(
        directives=[
            _directive(command="/x", description="x-desc"),
            _directive(command="/y", description="y-desc"),
        ]
    )
    pairs = registry.help_entries()
    assert dict(pairs) == {"/x": "x-desc", "/y": "y-desc"}


def test_registry_state_matrix_derives_from_metadata() -> None:
    registry = DirectiveRegistry(
        directives=[
            _directive(
                command="/x", requires=frozenset({ProjectState.INITIALIZED})
            ),
            _directive(
                command="/y",
                requires=frozenset(
                    {ProjectState.WRITING, ProjectState.HAS_TOC}
                ),
            ),
        ]
    )
    matrix = registry.state_matrix()
    assert matrix["/x"] == frozenset({ProjectState.INITIALIZED})
    assert matrix["/y"] == frozenset(
        {ProjectState.WRITING, ProjectState.HAS_TOC}
    )


# ---------------------------------------------------------------------------
# DirectiveRegistry: validation
# ---------------------------------------------------------------------------


def test_registry_rejects_directive_with_empty_command() -> None:
    with pytest.raises(Exception):  # SkillError
        DirectiveRegistry(directives=[_directive(command="")])


def test_registry_rejects_directive_with_empty_description() -> None:
    with pytest.raises(Exception):  # SkillError
        DirectiveRegistry(directives=[_directive(description="")])


def test_registry_rejects_directive_with_empty_requires_states() -> None:
    from writer.skills.errors import SkillError

    with pytest.raises(SkillError):
        DirectiveRegistry(
            directives=[_directive(requires=frozenset())]
        )


# ---------------------------------------------------------------------------
# Last-write-wins (Replace semantics)
# ---------------------------------------------------------------------------


def test_registry_later_directive_wins(tmp_path: Path) -> None:
    original = _directive(command="/x", description="original")
    override = _directive(command="/x", description="override")
    registry = DirectiveRegistry(directives=[original, override])
    assert registry.get("/x").description == "override"