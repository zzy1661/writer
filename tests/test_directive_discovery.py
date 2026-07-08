"""Tests for the Markdown SKILL.md directive discovery layer (chg-markdown-skills).

Covers:
- :func:`writer.skills.directive_discovery.discover_directives` — project-level scan
- :func:`writer.skills.directive_discovery.discover_shipped_directives` — package internals
- :func:`writer.skills.directive_discovery.resolve_references` — @reference syntax

Discovery now uses YAML frontmatter parsing (replacing the prior
Python importlib loader). Each SKILL.md is a self-contained
directive: command + description + requires_states in frontmatter,
Markdown body below.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from writer.skills import (
    discover_directives,
    discover_shipped_directives,
    resolve_references,
)

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_skill_md(
    skill_dir: Path,
    command: str,
    description: str = "测试 directive",
    requires_states: list[str] | None = None,
    body: str = "## 步骤\n\n1. 读文件\n2. 写文件\n",
) -> Path:
    """Write a minimal valid SKILL.md into ``<skill_dir>/SKILL.md``."""

    skill_dir.mkdir(parents=True, exist_ok=True)
    states = requires_states or ["S1"]
    front = (
        f"---\n"
        f"command: {command}\n"
        f"description: {description}\n"
        f"requires_states: {states}\n"
        f"---\n"
    )
    path = skill_dir / "SKILL.md"
    path.write_text(front + body, encoding="utf-8")
    return path


def _write_reference(skill_dir: Path, relpath: str, content: str) -> Path:
    refs_dir = skill_dir / "references"
    target = refs_dir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


def _write_script(skill_dir: Path, relpath: str, content: str) -> Path:
    scripts_dir = skill_dir / "scripts"
    target = scripts_dir / relpath
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    return target


# ---------------------------------------------------------------------------
# discover_directives: file-level
# ---------------------------------------------------------------------------


def test_discover_directives_no_skills_dir_returns_empty(tmp_path: Path) -> None:
    assert discover_directives(tmp_path) == []


def test_discover_directives_empty_dir_returns_empty(tmp_path: Path) -> None:
    (tmp_path / ".writer" / "skills").mkdir(parents=True)
    assert discover_directives(tmp_path) == []


def test_discover_directives_loads_valid_skill(tmp_path: Path) -> None:
    _write_skill_md(tmp_path / ".writer" / "skills" / "大纲", command="/大纲")
    directives = discover_directives(tmp_path)
    assert len(directives) == 1
    assert directives[0].command == "/大纲"


def test_discover_directives_skips_hidden_directories(tmp_path: Path) -> None:
    skills_dir = tmp_path / ".writer" / "skills"
    skills_dir.mkdir(parents=True)
    _write_skill_md(skills_dir / "_draft", command="/draft")
    _write_skill_md(skills_dir / ".hidden", command="/hidden")
    _write_skill_md(skills_dir / "valid", command="/valid")
    directives = discover_directives(tmp_path)
    assert [d.command for d in directives] == ["/valid"]


def test_discover_directives_skips_directory_without_skill_md(tmp_path: Path) -> None:
    """A directory containing only ``references/`` is not a directive."""
    skills_dir = tmp_path / ".writer" / "skills"
    (skills_dir / "no_skill_md" / "references").mkdir(parents=True)
    (skills_dir / "no_skill_md" / "references" / "x.md").write_text("x", encoding="utf-8")
    _write_skill_md(skills_dir / "real", command="/real")
    directives = discover_directives(tmp_path)
    assert [d.command for d in directives] == ["/real"]


# ---------------------------------------------------------------------------
# discover_directives: frontmatter + content
# ---------------------------------------------------------------------------


def test_discover_directives_parses_frontmatter_and_body(tmp_path: Path) -> None:
    _write_skill_md(
        tmp_path / ".writer" / "skills" / "大纲",
        command="/大纲",
        description="生成或查看大纲",
        body="## 步骤\n\n1. 读 outline/premise.md\n",
    )
    directives = discover_directives(tmp_path)
    assert directives[0].command == "/大纲"
    assert directives[0].description == "生成或查看大纲"
    assert directives[0].body.startswith("## 步骤")
    # requires_states: ["S1"] parses to INITIALIZED
    from writer.project import ProjectState

    assert ProjectState.INITIALIZED in directives[0].requires_states


def test_discover_directives_accepts_state_names(tmp_path: Path) -> None:
    """ProjectState NAMES (e.g. ``INITIALIZED``) are accepted, not just values."""
    _write_skill_md(
        tmp_path / ".writer" / "skills" / "test",
        command="/test",
        requires_states=["INITIALIZED", "HAS_OUTLINE"],
    )
    directives = discover_directives(tmp_path)
    assert len(directives) == 1
    assert "INITIALIZED" in [s.name for s in directives[0].requires_states]


def test_discover_directives_loads_references(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".writer" / "skills" / "大纲"
    _write_skill_md(skill_dir, command="/大纲")
    _write_reference(skill_dir, "template.md", "# 4-Act Template\n\nbody")
    _write_reference(skill_dir, "examples.md", "# Examples\n\nbody")

    directives = discover_directives(tmp_path)
    assert set(directives[0].references.keys()) == {"template.md", "examples.md"}
    assert directives[0].references["template.md"].startswith("# 4-Act Template")


def test_discover_directives_references_keyed_by_path_within_references_dir(
    tmp_path: Path,
) -> None:
    """`references/foo.md` is keyed as `foo.md`, NOT as `references/foo.md`."""
    skill_dir = tmp_path / ".writer" / "skills" / "x"
    _write_skill_md(skill_dir, command="/x")
    _write_reference(skill_dir, "template.md", "body")

    directives = discover_directives(tmp_path)
    assert "template.md" in directives[0].references
    assert "references/template.md" not in directives[0].references


def test_discover_directives_lists_scripts_without_loading(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".writer" / "skills" / "大纲"
    _write_skill_md(skill_dir, command="/大纲")
    _write_script(skill_dir, "format_outline.py", "print('hello')\n")

    directives = discover_directives(tmp_path)
    assert directives[0].scripts == ["scripts/format_outline.py"]


def test_discover_directives_skips_non_md_references(tmp_path: Path) -> None:
    skill_dir = tmp_path / ".writer" / "skills" / "大纲"
    _write_skill_md(skill_dir, command="/大纲")
    refs = skill_dir / "references"
    refs.mkdir()
    (refs / "image.png").write_bytes(b"\x89PNG")
    _write_reference(skill_dir, "template.md", "x")

    directives = discover_directives(tmp_path)
    assert "image.png" not in directives[0].references
    assert "template.md" in directives[0].references


# ---------------------------------------------------------------------------
# discover_directives: failure modes
# ---------------------------------------------------------------------------


def test_discover_directives_skips_invalid_yaml(tmp_path: Path, caplog) -> None:
    skills_dir = tmp_path / ".writer" / "skills"
    skills_dir.mkdir(parents=True)
    bad = skills_dir / "bad"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\ncommand: /bad\ndescription: oops\n: this is invalid yaml: :\n---\nbody\n",
        encoding="utf-8",
    )
    _write_skill_md(skills_dir / "good", command="/good")

    import logging

    with caplog.at_level(logging.WARNING, logger="writer.skills.directive_discovery"):
        directives = discover_directives(tmp_path)

    assert [d.command for d in directives] == ["/good"]


def test_discover_directives_skips_missing_command(tmp_path: Path, caplog) -> None:
    skills_dir = tmp_path / ".writer" / "skills"
    skills_dir.mkdir(parents=True)
    bad = skills_dir / "no_command"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\ndescription: missing command\nrequires_states: [S1]\n---\nbody\n",
        encoding="utf-8",
    )

    import logging

    with caplog.at_level(logging.WARNING, logger="writer.skills.directive_discovery"):
        directives = discover_directives(tmp_path)
    assert directives == []


def test_discover_directives_skips_unknown_state(tmp_path: Path, caplog) -> None:
    skills_dir = tmp_path / ".writer" / "skills"
    skills_dir.mkdir(parents=True)
    bad = skills_dir / "bad_state"
    bad.mkdir()
    (bad / "SKILL.md").write_text(
        "---\ncommand: /bad\ndescription: bad state\nrequires_states: [S99]\n---\nbody\n",
        encoding="utf-8",
    )

    import logging

    with caplog.at_level(logging.WARNING, logger="writer.skills.directive_discovery"):
        directives = discover_directives(tmp_path)
    assert directives == []


# ---------------------------------------------------------------------------
# discover_shipped_directives
# ---------------------------------------------------------------------------


def test_discover_shipped_directives_returns_four() -> None:
    directives = discover_shipped_directives()
    commands = sorted(d.command for d in directives)
    assert commands == sorted(["/大纲", "/目录", "/续写", "/改"])


def test_discover_shipped_directives_have_references() -> None:
    directives = discover_shipped_directives()
    for d in directives:
        assert d.references, f"shipped {d.command} must have at least one reference"


def test_discover_shipped_directives_have_requires_states() -> None:
    directives = discover_shipped_directives()
    for d in directives:
        assert d.requires_states, f"shipped {d.command} must have requires_states"


# ---------------------------------------------------------------------------
# resolve_references
# ---------------------------------------------------------------------------


def test_resolve_references_returns_ordered_pairs() -> None:
    body = "@reference a.md\ndo something\n@reference b.md\n@reference a.md again\n"
    refs = {
        "a.md": "AAA",
        "b.md": "BBB",
    }
    out = resolve_references(body, refs)
    assert out == [("a.md", "AAA"), ("b.md", "BBB")]


def test_resolve_references_deduplicates() -> None:
    body = "@reference a.md\n@reference a.md\n@reference b.md\n@reference a.md\n"
    refs = {"a.md": "AAA", "b.md": "BBB"}
    out = resolve_references(body, refs)
    assert out == [("a.md", "AAA"), ("b.md", "BBB")]


def test_resolve_references_skips_unknown_paths(caplog) -> None:
    import logging

    body = "@reference known.md\n@reference unknown.md\n"
    refs = {"known.md": "OK"}
    with caplog.at_level(logging.WARNING, logger="writer.skills.directive_discovery"):
        out = resolve_references(body, refs)
    assert out == [("known.md", "OK")]


def test_resolve_references_returns_empty_when_no_references() -> None:
    body = "no references here"
    refs = {"a.md": "AAA"}
    assert resolve_references(body, refs) == []


def test_resolve_references_returns_empty_when_references_empty() -> None:
    body = "@reference a.md"
    assert resolve_references(body, {}) == []
