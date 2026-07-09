"""Unit tests for :mod:`writer.agents` (AgentRegistry + parser + drift detection).

Added 2026-07-09 per ``fea-agent-mirror``. The tests cover:

* YAML frontmatter parsing (:func:`parse_agent_file`)
* :class:`AgentRegistry` last-write-wins + lookup API
* :func:`built_agent_registry` layering (built-in + project + entry-point)
* Description truncation + agent-count cap in
  :meth:`AgentRegistry.descriptions`
* BUILTIN_AGENT_SOURCES sha256 drift detection

Mirrors the test layout of :mod:`tests.test_skill_loader` so the
two discovery stacks stay symmetric.
"""

from __future__ import annotations

import logging
from pathlib import Path
from textwrap import dedent

import pytest

from writer.agents import (
    AgentRegistry,
    AgentRegistryError,
    builtin_agent_registry,
    parse_agent_file,
)

# ---------------------------------------------------------------------------
# parse_agent_file
# ---------------------------------------------------------------------------


def test_parse_agent_file_extracts_frontmatter_and_body(tmp_path: Path) -> None:
    """Valid YAML frontmatter + body parse into an Agent."""

    md = tmp_path / "demo.md"
    md.write_text(
        dedent(
            """\
            ---
            name: demo
            description: |
              测试 agent — 用于单元测试。
              适合单元测试 / 集成测试 / 端到端测试三类场景。
              不适合生产环境。
            genre: other
            tools: []
            ---

            # Test agent body

            This is the body of the test agent.
            """
        ),
        encoding="utf-8",
    )

    agent = parse_agent_file(md)
    assert agent.name == "demo"
    assert agent.genre == "other"
    assert "测试 agent" in agent.description
    assert agent.tools_allowlist == ()
    assert "Test agent body" in agent.body


@pytest.mark.parametrize(
    "missing_field",
    ["name", "description", "genre"],
)
def test_parse_agent_file_raises_on_missing_required_field(
    tmp_path: Path, missing_field: str
) -> None:
    """Any missing required frontmatter key raises AgentRegistryError."""

    fields = {
        "name": "demo",
        "description": "A test agent with a sufficiently long description.",
        "genre": "other",
    }
    fields.pop(missing_field)
    frontmatter_lines = ["---"]
    for key, value in fields.items():
        if isinstance(value, str):
            frontmatter_lines.append(f"{key:14s}: {value!r}")
        else:
            frontmatter_lines.append(f"{key:14s}: {value}")
    frontmatter_lines.append("---")
    frontmatter_lines.append("")
    frontmatter_lines.append("# body")
    text = "\n".join(frontmatter_lines)
    md = tmp_path / "bad.md"
    md.write_text(text, encoding="utf-8")

    with pytest.raises(AgentRegistryError) as exc_info:
        parse_agent_file(md)
    assert missing_field in str(exc_info.value)


def test_parse_agent_file_raises_on_empty_body(tmp_path: Path) -> None:
    """Empty body → AgentRegistryError (the field is required)."""

    md = tmp_path / "empty_body.md"
    md.write_text(
        "---\nname: empty\ndescription: 一个没有 body 的 agent。\ngenre: other\n---\n",
        encoding="utf-8",
    )
    with pytest.raises(AgentRegistryError) as exc_info:
        parse_agent_file(md)
    assert "body" in str(exc_info.value).lower()


def test_parse_agent_file_description_length_must_be_in_range(tmp_path: Path) -> None:
    """Description shorter than 50 chars (or longer than 500) is rejected."""

    short = tmp_path / "short.md"
    short.write_text(
        "---\nname: short\ndescription: 太短了。\ngenre: other\n---\n\nbody\n",
        encoding="utf-8",
    )
    with pytest.raises(AgentRegistryError) as exc_info:
        parse_agent_file(short)
    assert "description" in str(exc_info.value).lower()


# ---------------------------------------------------------------------------
# AgentRegistry
# ---------------------------------------------------------------------------


def _make_agent(name: str, genre: str = "other", body: str = "x" * 60) -> object:
    """Build a minimal Agent for tests, bypassing YAML parsing."""

    from writer.agents.protocol import Agent  # local: avoid import-time cycle

    return Agent(
        name=name,
        description=f"{name} 的测试描述文本 — 用于构造 AgentRegistry。",
        genre=genre,
        body=body,
    )


def test_agent_registry_last_write_wins_overrides_by_name() -> None:
    """Project agent with same name as built-in takes precedence."""

    built_in = _make_agent("history", genre="other", body="BUILTIN body")
    project = _make_agent("history", genre="历史", body="PROJECT body")
    reg = AgentRegistry(agents=[built_in, project])
    assert reg.get("history") is project
    assert reg.get("history").genre == "历史"


def test_agent_registry_last_write_wins_within_agents_list() -> None:
    """The registry is last-write-wins even within a single ``agents=`` list.

    Within-layer duplicate detection lives in the discovery layer
    (:func:`writer.agents.agent_discovery.discover_agents` /
    :func:`discover_shipped_agents`) so the registry itself stays a
    pure data structure: callers (the discovery layer or tests) are
    responsible for the cross-source uniqueness check.
    """

    a = _make_agent("dup", genre="other", body="first body")
    b = _make_agent("dup", genre="other", body="second body")
    reg = AgentRegistry(agents=[a, b])
    assert reg.get("dup") is b
    assert reg.get("dup").body == "second body"


def test_agent_registry_descriptions_returns_sorted_view() -> None:
    """descriptions() returns ``[{name, description, genre}]`` sorted by name."""

    agents = [
        _make_agent("zebra", genre="other"),
        _make_agent("alpha", genre="历史"),
        _make_agent("mango", genre="言情"),
    ]
    reg = AgentRegistry(agents=agents)
    descs = reg.descriptions()
    assert [d["name"] for d in descs] == ["alpha", "mango", "zebra"]
    assert all(
        set(d.keys()) == {"name", "description", "genre"} for d in descs
    )


def test_agent_registry_descriptions_truncates_long_descriptions() -> None:
    """Descriptions longer than 200 chars are truncated."""

    from writer.agents.protocol import Agent  # local: avoid import-time cycle

    long_desc = "x" * 500
    agent = Agent(
        name="long",
        description=long_desc,
        genre="other",
        body="body",
    )
    reg = AgentRegistry(agents=[agent])
    descs = reg.descriptions()
    assert len(descs) == 1
    assert len(descs[0]["description"]) == 200


def test_agent_registry_descriptions_caps_at_sixteen() -> None:
    """Registry with >16 agents caps the description list at 16 (with WARNING)."""

    agents = [_make_agent(f"agent_{i:02d}") for i in range(20)]
    reg = AgentRegistry(agents=agents)
    descs = reg.descriptions()
    assert len(descs) == 16


def test_agent_registry_require_raises_for_missing_name() -> None:
    """require() surfaces a clear error rather than returning None."""

    reg = AgentRegistry(agents=[_make_agent("alpha")])
    with pytest.raises(AgentRegistryError) as exc_info:
        reg.require("nonexistent")
    assert "nonexistent" in str(exc_info.value)


# ---------------------------------------------------------------------------
# discover_project_agents
# ---------------------------------------------------------------------------


def test_discover_project_agents_empty_dir_returns_empty_list(tmp_path: Path) -> None:
    """Empty project → no agents discovered, no error raised."""

    from writer.agents.agent_discovery import discover_agents

    (tmp_path / ".writer" / "agents").mkdir(parents=True)
    assert discover_agents(tmp_path) == []


def test_discover_project_agents_one_md(tmp_path: Path) -> None:
    """One valid .md file in .writer/agents/ is loaded."""

    from writer.agents.agent_discovery import discover_agents

    agents_dir = tmp_path / ".writer" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "custom.md").write_text(
        dedent(
            """\
            ---
            name: custom
            description: |
              测试用 project agent。
              适合单元测试 / 集成测试 / 端到端测试三类场景。
              不适合生产环境。
            genre: other
            tools: []
            ---

            body
            """
        ),
        encoding="utf-8",
    )
    result = discover_agents(tmp_path)
    assert len(result) == 1
    assert result[0].name == "custom"


def test_built_agent_registry_includes_builtin_and_project(tmp_path: Path) -> None:
    """built_agent_registry composes built-in + project agents."""

    from writer.agents import built_agent_registry

    # Set up a project with one custom .md
    agents_dir = tmp_path / ".writer" / "agents"
    agents_dir.mkdir(parents=True)
    (agents_dir / "history.md").write_text(
        dedent(
            """\
            ---
            name: history
            description: |
              项目级 history agent — 覆盖内置版本。
              适合朝代背景 / 年表顺序 / 史实考证三类场景。
              不适合纯虚构 / 修真升级 / 言情节拍。
            genre: 历史
            tools: []
            ---

            PROJECT body
            """
        ),
        encoding="utf-8",
    )

    reg = built_agent_registry(project_root=tmp_path)
    names = reg.names()
    # 4 built-in + 1 project override
    assert names == ["history", "other", "romance", "xuanhuan"]
    # The project version wins for "history"
    assert reg.get("history").body.strip() == "PROJECT body"


# ---------------------------------------------------------------------------
# builtin_agent_registry smoke
# ---------------------------------------------------------------------------


def test_builtin_agent_registry_returns_four_shipped_agents() -> None:
    """Smoke test: the built-in registry returns the 4 shipped agents."""

    reg = builtin_agent_registry()
    assert reg.names() == ["history", "other", "romance", "xuanhuan"]


# ---------------------------------------------------------------------------
# BUILTIN_AGENT_SOURCES drift detection
# ---------------------------------------------------------------------------


def test_drift_detection_logs_warning_on_sha_mismatch(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Tampering with a shipped .md emits a WARNING at registry construction."""

    from writer.agents import builtin_sources
    from writer.agents.registry import built_agent_registry

    # Read the shipped 历史.md and corrupt it (no actual file change; we
    # force the registry to compare against a bogus sha).
    original_entry = builtin_sources.BUILTIN_AGENT_SOURCES
    bogus_entry = type(original_entry[0])(
        mirror_filename=original_entry[1].mirror_filename,  # 历史.md
        source_module=original_entry[1].source_module,
        source_sha256="0" * 64,  # obviously wrong
    )
    builtin_sources.BUILTIN_AGENT_SOURCES = (original_entry[0], bogus_entry) + original_entry[2:]
    try:
        with caplog.at_level(logging.WARNING, logger="writer.agents.registry"):
            built_agent_registry(project_root=tmp_path)
        assert any("drifted" in r.message for r in caplog.records)
    finally:
        builtin_sources.BUILTIN_AGENT_SOURCES = original_entry
