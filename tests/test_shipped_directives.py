"""Tests for the 4 shipped SKILL.md directive packages (chg-markdown-skills).

Verifies that ``src/writer/skills/_shipped/`` ships with the expected
structure (SKILL.md + references/*.md for each of the 4 commands),
the frontmatter parses cleanly, and the references contain real
content (not stubs).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from writer.skills.directive_discovery import discover_shipped_directives

_SHIPPED_ROOT = Path(__file__).resolve().parent.parent / "src" / "writer" / "skills" / "_shipped"

_SHIPPED_COMMANDS = ["/大纲", "/目录", "/续写", "/改"]


# ---------------------------------------------------------------------------
# File structure
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", _SHIPPED_COMMANDS)
def test_shipped_directive_directory_exists(command: str) -> None:
    basename = command.lstrip("/")
    assert (_SHIPPED_ROOT / basename).is_dir(), (
        f"shipped directive dir missing: {basename}"
    )


@pytest.mark.parametrize("command", _SHIPPED_COMMANDS)
def test_shipped_skill_md_exists(command: str) -> None:
    basename = command.lstrip("/")
    skill_md = _SHIPPED_ROOT / basename / "SKILL.md"
    assert skill_md.is_file(), f"SKILL.md missing for {command}"


@pytest.mark.parametrize("command", _SHIPPED_COMMANDS)
def test_shipped_references_dir_has_md(command: str) -> None:
    basename = command.lstrip("/")
    refs_dir = _SHIPPED_ROOT / basename / "references"
    assert refs_dir.is_dir(), f"references/ missing for {command}"
    md_files = list(refs_dir.glob("*.md"))
    assert len(md_files) >= 1, f"at least one *.md reference required for {command}"


# ---------------------------------------------------------------------------
# Content quality
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("command", _SHIPPED_COMMANDS)
def test_shipped_reference_files_meet_size_floor(command: str) -> None:
    """Each reference must be at least 500 bytes (real content, not stub)."""

    basename = command.lstrip("/")
    refs_dir = _SHIPPED_ROOT / basename / "references"
    for md in refs_dir.glob("*.md"):
        assert md.stat().st_size >= 500, (
            f"{md} is too small ({md.stat().st_size} bytes); "
            "shipped references must be real content"
        )


# ---------------------------------------------------------------------------
# Discoverable
# ---------------------------------------------------------------------------


def test_shipped_directives_discoverable() -> None:
    directives = discover_shipped_directives()
    commands = {d.command for d in directives}
    assert commands == set(_SHIPPED_COMMANDS)


def test_shipped_directives_have_meaningful_bodies() -> None:
    """Body length should reflect real instructions, not stubs."""

    directives = discover_shipped_directives()
    for d in directives:
        assert len(d.body) >= 500, (
            f"shipped {d.command} body too short ({len(d.body)} chars)"
        )


def test_shipped_directives_reference_files_via_at_reference() -> None:
    """Each body should reference its companion references/ files.

    Body mentions may use either ``@reference template.md`` or
    ``@reference references/template.md`` — both should resolve to the
    same file. This test normalises both forms before comparing.
    """

    directives = discover_shipped_directives()
    for d in directives:
        import re

        body_refs = set()
        for m in re.finditer(r"@reference\s+([^\s]+)", d.body):
            raw = m.group(1)
            # Normalise ``references/foo.md`` → ``foo.md`` to match
            # how the loader keys the references dict.
            normalised = (
                raw[len("references/") :] if raw.startswith("references/") else raw
            )
            body_refs.add(normalised)
        available = set(d.references.keys())
        # At least one body reference must exist in the references dict.
        assert body_refs & available, (
            f"shipped {d.command} has @reference mentions "
            f"({body_refs}) that don't match references/ {available}"
        )


def test_shipped_directives_have_real_descriptions() -> None:
    directives = discover_shipped_directives()
    expected = {
        "/大纲": "生成或查看大纲",
        "/目录": "生成或查看章节目录",
        "/续写": "继续未完成章节",
        "/改": "修改章节内容",
    }
    for d in directives:
        assert d.description == expected[d.command], (
            f"shipped {d.command} description drift: {d.description!r}"
        )