"""Tests for the project-level skill discovery layer (chg-project-skills).

Covers:
- :func:`writer.skills.loader.discover_project_skills` — filesystem scan
- :data:`writer.skills.builtin_sources.BUILTIN_SKILL_SOURCES` — registry
  shape (4 entries for the 4 built-in skills)
- :func:`writer.skills.registry.built_skill_registry(project_root=...)` —
  the new ``project_root`` kwarg wires the loader into the registry
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from writer.skills import (
    BUILTIN_SKILL_SOURCES,
    OutlineSkill,
    Skill,
    built_skill_registry,
    discover_project_skills,
)
from writer.skills.builtin_sources import MIRROR_HEADER_TEMPLATE

if TYPE_CHECKING:

    pass


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _write_skill(
    skills_dir: Path,
    basename: str,
    *,
    class_name: str = "ProjectSkill",
    command: str = "/项目",
    description: str = "项目级 skill 测试",
    md_body: str | None = "可调的 LLM 指令",
    extra_instructions: str = "",
) -> Path:
    """Write a minimal valid project skill file under ``skills_dir``.

    Returns the path of the written ``.py``. The generated class is
    a real ``Skill`` subclass (it declares the four required
    attributes and a stub ``run``).
    """

    skills_dir.mkdir(parents=True, exist_ok=True)
    body = (
        f"from writer.project import ProjectState\n"
        f"from writer.skills import Skill\n\n"
        f"class {class_name}:\n"
        f"    command = {command!r}\n"
        f"    description = {description!r}\n"
        f"    requires_states = frozenset({{ProjectState.INITIALIZED}})\n"
        f"    extra_instructions = {extra_instructions!r}\n\n"
        f"    async def run(self, ctx, deps, cfg):\n"
        f"        if False:\n"
        f"            yield None\n"
    )
    path = skills_dir / f"{basename}.py"
    path.write_text(body, encoding="utf-8")
    if md_body is not None:
        (skills_dir / f"{basename}.md").write_text(
            f"# {command}\n\n{md_body}\n", encoding="utf-8"
        )
    return path


def _skills_dir(project_root: Path) -> Path:
    return project_root / ".writer" / "skills"


# ---------------------------------------------------------------------------
# discover_project_skills: file-level behavior
# ---------------------------------------------------------------------------


def test_discover_project_skills_no_dir_returns_empty(tmp_path: Path) -> None:
    assert discover_project_skills(tmp_path) == []


def test_discover_project_skills_empty_dir_returns_empty(tmp_path: Path) -> None:
    _skills_dir(tmp_path).mkdir(parents=True)
    assert discover_project_skills(tmp_path) == []


def test_discover_project_skills_returns_valid_skill(tmp_path: Path) -> None:
    _write_skill(_skills_dir(tmp_path), "项目", command="/项目")
    skills = discover_project_skills(tmp_path)
    assert len(skills) == 1
    assert skills[0].command == "/项目"


def test_discover_project_skills_skips_underscore_and_dotfiles(
    tmp_path: Path,
) -> None:
    skills_dir = _skills_dir(tmp_path)
    skills_dir.mkdir(parents=True)
    (skills_dir / "_hidden.py").write_text("x = 1", encoding="utf-8")
    (skills_dir / ".dotfile.py").write_text("x = 1", encoding="utf-8")
    (skills_dir / "valid.py").write_text(
        "from writer.project import ProjectState\n"
        "class P:\n"
        "    command = '/p'\n"
        "    description = 'p'\n"
        "    requires_states = frozenset({ProjectState.INITIALIZED})\n"
        "    extra_instructions = ''\n"
        "    async def run(self, ctx, deps, cfg):\n"
        "        if False: yield None\n",
        encoding="utf-8",
    )
    skills = discover_project_skills(tmp_path)
    assert [s.command for s in skills] == ["/p"]


def test_discover_project_skills_does_not_load_dunder_dirs(tmp_path: Path) -> None:
    skills_dir = _skills_dir(tmp_path)
    skills_dir.mkdir(parents=True)
    (skills_dir / "__pycache__").mkdir()
    (skills_dir / "__pycache__" / "x.py").write_text("x = 1", encoding="utf-8")
    assert discover_project_skills(tmp_path) == []


# ---------------------------------------------------------------------------
# discover_project_skills: skill shape
# ---------------------------------------------------------------------------


def test_discover_project_skills_accepts_skill_subclass(tmp_path: Path) -> None:
    """A module declaring one ``Skill`` subclass is loaded and instantiated."""
    _write_skill(_skills_dir(tmp_path), "项目", command="/项目")
    skills = discover_project_skills(tmp_path)
    assert isinstance(skills[0], Skill)


def test_discover_project_skills_accepts_prebuilt_instance(tmp_path: Path) -> None:
    """A module exposing a top-level ``Skill`` instance is used as-is."""
    skills_dir = _skills_dir(tmp_path)
    skills_dir.mkdir(parents=True)
    (skills_dir / "项目.py").write_text(
        "from writer.project import ProjectState\n"
        "from writer.skills import Skill\n\n"
        "class _ProjectSkill:\n"
        "    command = '/项目'\n"
        "    description = 'project'\n"
        "    requires_states = frozenset({ProjectState.INITIALIZED})\n"
        "    extra_instructions = ''\n"
        "    async def run(self, ctx, deps, cfg):\n"
        "        if False: yield None\n\n"
        "项目 = _ProjectSkill()\n",
        encoding="utf-8",
    )
    skills = discover_project_skills(tmp_path)
    assert len(skills) == 1
    assert skills[0].command == "/项目"


# ---------------------------------------------------------------------------
# discover_project_skills: companion Markdown
# ---------------------------------------------------------------------------


def test_discover_project_skills_loads_markdown_into_extra_instructions(
    tmp_path: Path,
) -> None:
    _write_skill(
        _skills_dir(tmp_path),
        "项目",
        command="/项目",
        md_body="可调的 LLM 指令 v2",
    )
    skills = discover_project_skills(tmp_path)
    # The fixture writes ``# <command>\n\n<body>`` and the loader
    # strips the trailing newline; the title line and blank are kept.
    assert skills[0].extra_instructions == "# /项目\n\n可调的 LLM 指令 v2"


def test_discover_project_skills_missing_markdown_defaults_to_empty(
    tmp_path: Path,
) -> None:
    _write_skill(_skills_dir(tmp_path), "项目", command="/项目", md_body=None)
    skills = discover_project_skills(tmp_path)
    assert skills[0].extra_instructions == ""


# ---------------------------------------------------------------------------
# discover_project_skills: failure modes
# ---------------------------------------------------------------------------


def test_discover_project_skills_syntax_error_does_not_block_others(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    skills_dir = _skills_dir(tmp_path)
    skills_dir.mkdir(parents=True)
    (skills_dir / "broken.py").write_text("def f(:\n    pass\n", encoding="utf-8")
    _write_skill(skills_dir, "valid", command="/valid")

    with caplog.at_level("WARNING", logger="writer.skills.loader"):
        skills = discover_project_skills(tmp_path)

    assert [s.command for s in skills] == ["/valid"]
    assert any("broken.py" in r.message for r in caplog.records)


def test_discover_project_skills_module_without_skill_is_skipped(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    skills_dir = _skills_dir(tmp_path)
    skills_dir.mkdir(parents=True)
    (skills_dir / "no_skill.py").write_text("x = 42\n", encoding="utf-8")

    with caplog.at_level("WARNING", logger="writer.skills.loader"):
        skills = discover_project_skills(tmp_path)
    assert skills == []
    assert any("no_skill.py" in r.message for r in caplog.records)


def test_discover_project_skills_class_with_empty_command_is_skipped(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    skills_dir = _skills_dir(tmp_path)
    skills_dir.mkdir(parents=True)
    (skills_dir / "bad.py").write_text(
        "from writer.project import ProjectState\n"
        "from writer.skills import Skill\n\n"
        "class _Bad:\n"
        "    command = ''  # invalid: must start with /\n"
        "    description = 'x'\n"
        "    requires_states = frozenset({ProjectState.INITIALIZED})\n"
        "    extra_instructions = ''\n"
        "    async def run(self, ctx, deps, cfg):\n"
        "        if False: yield None\n",
        encoding="utf-8",
    )

    with caplog.at_level("WARNING", logger="writer.skills.loader"):
        skills = discover_project_skills(tmp_path)
    assert skills == []


def test_discover_project_skills_multiple_skill_subclasses_skipped(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    skills_dir = _skills_dir(tmp_path)
    skills_dir.mkdir(parents=True)
    (skills_dir / "two.py").write_text(
        "from writer.project import ProjectState\n"
        "class A:\n"
        "    command = '/a'\n"
        "    description = 'a'\n"
        "    requires_states = frozenset({ProjectState.INITIALIZED})\n"
        "    extra_instructions = ''\n"
        "    async def run(self, ctx, deps, cfg):\n"
        "        if False: yield None\n\n"
        "class B:\n"
        "    command = '/b'\n"
        "    description = 'b'\n"
        "    requires_states = frozenset({ProjectState.INITIALIZED})\n"
        "    extra_instructions = ''\n"
        "    async def run(self, ctx, deps, cfg):\n"
        "        if False: yield None\n",
        encoding="utf-8",
    )

    with caplog.at_level("WARNING", logger="writer.skills.loader"):
        skills = discover_project_skills(tmp_path)
    assert skills == []


# ---------------------------------------------------------------------------
# discover_project_skills: import hygiene
# ---------------------------------------------------------------------------


def test_discover_project_skills_registers_module_in_sys_modules(
    tmp_path: Path,
) -> None:
    """Loaded modules land in ``sys.modules`` so relative imports work."""
    skills_dir = _skills_dir(tmp_path)
    _write_skill(skills_dir, "项目", command="/项目")
    discover_project_skills(tmp_path)
    assert "writer_user_skill_项目" in sys.modules


def test_discover_project_skills_cleans_sys_modules_on_failure(
    tmp_path: Path,
) -> None:
    skills_dir = _skills_dir(tmp_path)
    skills_dir.mkdir(parents=True)
    (skills_dir / "broken.py").write_text("def f(:\n    pass\n", encoding="utf-8")

    discover_project_skills(tmp_path)
    assert "writer_user_skill_broken" not in sys.modules


# ---------------------------------------------------------------------------
# builtin_sources registry shape
# ---------------------------------------------------------------------------


def test_builtin_skill_sources_has_four_entries() -> None:
    assert len(BUILTIN_SKILL_SOURCES) == 4


def test_builtin_skill_sources_covers_all_built_in_commands() -> None:
    commands = {src.command for src in BUILTIN_SKILL_SOURCES}
    assert commands == {"/大纲", "/目录", "/续写", "/改"}


def test_builtin_skill_sources_mirror_filenames_match_commands() -> None:
    mapping = {
        "/大纲": "大纲",
        "/目录": "目录",
        "/续写": "续写",
        "/改": "改",
    }
    for src in BUILTIN_SKILL_SOURCES:
        assert src.mirror_filename == mapping[src.command]


def test_builtin_skill_sources_sha256_is_64_hex_chars() -> None:
    for src in BUILTIN_SKILL_SOURCES:
        assert len(src.source_sha256) == 64
        assert all(c in "0123456789abcdef" for c in src.source_sha256)


def test_builtin_skill_sources_sha256_matches_actual_source(tmp_path: Path) -> None:
    """The recorded SHA-256 must match the current source file.

    This protects against silent drift when a built-in skill evolves:
    if a contributor forgets to update BUILTIN_SKILL_SOURCES, this test
    fails, forcing them to regenerate the fingerprint.
    """
    import hashlib

    for src in BUILTIN_SKILL_SOURCES:
        module = importlib.import_module(src.source_module)
        actual = hashlib.sha256(Path(module.__file__).read_bytes()).hexdigest()
        assert actual == src.source_sha256, (
            f"{src.source_module} drifted; update BUILTIN_SKILL_SOURCES"
        )


def test_mirror_header_template_renders_without_error() -> None:
    out = MIRROR_HEADER_TEMPLATE.format(
        command="/x",
        source_module_last="x",
        class_name="X",
        source_sha256="0" * 64,
    )
    assert "/x" in out
    assert "0" * 64 in out


# ---------------------------------------------------------------------------
# built_skill_registry(project_root=...) wiring
# ---------------------------------------------------------------------------


def test_built_skill_registry_project_root_none_matches_legacy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``project_root=None`` (legacy) → no project skills added.

    Verified by patching entry-points to empty (so we know any added
    skill came from neither layer).
    """

    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: [],
    )
    registry = built_skill_registry(project_root=None)
    commands = set(registry.commands())
    assert commands == {"/大纲", "/目录", "/续写", "/改"}


def test_built_skill_registry_project_root_adds_project_layer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """When ``.writer/skills/`` contains a valid skill, the registry
    includes it."""
    _write_skill(_skills_dir(tmp_path), "项目", command="/项目")
    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: [],
    )
    registry = built_skill_registry(project_root=tmp_path)
    assert registry.get("/项目") is not None
    # Built-ins still present
    assert isinstance(registry.get("/大纲"), OutlineSkill)


def test_built_skill_registry_project_skill_overrides_builtin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A project skill whose ``command`` collides with a built-in
    REPLACES the built-in (per chg-project-skills Decision 8)."""
    skills_dir = _skills_dir(tmp_path)
    _write_skill(
        skills_dir,
        "项目大纲",
        command="/大纲",
        description="项目级 override",
    )
    monkeypatch.setattr(
        "writer.skills.registry.metadata.entry_points",
        lambda *, group: [],
    )

    registry = built_skill_registry(project_root=tmp_path)
    skill = registry.get("/大纲")
    assert skill is not None
    assert skill.description == "项目级 override"
    assert not isinstance(skill, OutlineSkill)


# ---------------------------------------------------------------------------
# workspace seeding: create_new_workspace mirrors all built-ins
# ---------------------------------------------------------------------------


def test_create_new_workspace_seeds_skill_mirrors(tmp_path: Path) -> None:
    """`writer new` produces 4 ``.py`` + 4 ``.md`` files under .writer/skills/."""
    from writer.project import create_new_workspace

    workspace = create_new_workspace("测试项目", tmp_path)
    skills_dir = workspace.root / ".writer" / "skills"

    expected_py = {"大纲.py", "目录.py", "续写.py", "改.py"}
    expected_md = {"大纲.md", "目录.md", "续写.md", "改.md"}
    assert {p.name for p in skills_dir.glob("*.py")} == expected_py
    assert {p.name for p in skills_dir.glob("*.md")} == expected_md


def test_create_new_workspace_skill_mirror_contains_class(
    tmp_path: Path,
) -> None:
    """Each mirrored ``.py`` contains the corresponding class definition."""
    from writer.project import create_new_workspace

    workspace = create_new_workspace("测试项目", tmp_path)
    outline_mirror = (workspace.root / ".writer" / "skills" / "大纲.py").read_text(
        encoding="utf-8"
    )
    assert "class OutlineSkill" in outline_mirror
    assert "command = \"/大纲\"" in outline_mirror
    # The header explains the override semantics
    assert "项目级 override" in outline_mirror or "override" in outline_mirror


def test_create_workspace_does_not_seed_skill_mirrors(tmp_path: Path) -> None:
    """The low-level ``create_workspace`` (no ``with_writer_meta``) does NOT
    create skill files — mirrors are only for ``create_new_workspace``."""
    from writer.project import create_workspace

    create_workspace("no-mirror", tmp_path)
    skills_dir = tmp_path / "no-mirror" / ".writer" / "skills"
    # .gitkeep may or may not be there; what MUST NOT exist is a real .py
    assert list(skills_dir.glob("*.py")) == []
    assert list(skills_dir.glob("*.md")) == []


def test_create_new_workspace_does_not_overwrite_existing_skills(
    tmp_path: Path,
) -> None:
    """Re-seeding must not clobber the user's hand-edited skill files."""
    from writer.project import create_new_workspace

    first = create_new_workspace("re-seed", tmp_path)
    user_path = first.root / ".writer" / "skills" / "大纲.py"
    user_path.write_text("# USER EDIT\n", encoding="utf-8")

    # Re-create the same project; since the directory already exists
    # we expect a FileExistsError, so we exercise the seeding path by
    # re-calling the helper with force=True via the workspace module.
    from writer.project.workspace import _seed_skill_mirrors

    _seed_skill_mirrors(first.root / ".writer", force=False)
    assert user_path.read_text(encoding="utf-8") == "# USER EDIT\n"


def test_create_new_workspace_force_overwrites_skill_mirrors(
    tmp_path: Path,
) -> None:
    from writer.project import create_new_workspace
    from writer.project.workspace import _seed_skill_mirrors

    first = create_new_workspace("re-seed-force", tmp_path)
    user_path = first.root / ".writer" / "skills" / "大纲.py"
    user_path.write_text("# USER EDIT\n", encoding="utf-8")

    _seed_skill_mirrors(first.root / ".writer", force=True)
    text = user_path.read_text(encoding="utf-8")
    assert text != "# USER EDIT\n"
    assert "class OutlineSkill" in text
