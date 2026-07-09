"""Project-level and shipped-agent discovery.

Public surface (per ``fea-agent-mirror``):

* :func:`discover_agents` — scan a project's
  ``<project_root>/.writer/agents/*.md`` files and load every
  well-formed :class:`Agent`.
* :func:`discover_shipped_agents` — list the 4 built-in agents
  shipped at ``writer/agents/_shipped/`` via ``importlib.resources``.
* :func:`discover_entry_point_agents` — entry-point plugin hook.

All failures are logged at WARNING and skipped — a single broken
agent MUST NOT prevent other agents from loading and MUST NOT
prevent the REPL from starting.
"""

from __future__ import annotations

import importlib.resources
import logging
import re
from importlib import metadata
from pathlib import Path

log = logging.getLogger(__name__)


#: Frontmatter pattern: ``---\n<yaml>---\n<body>``. We require both
#: delimiters to be present (the file MUST be a complete YAML doc).
#: Multiline frontmatter is supported; the closing ``---`` MUST be
#: on its own line.
_FRONTMATTER_PATTERN = re.compile(
    r"\A---\s*\n(?P<front>.*?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)


def discover_agents(project_root: Path) -> list[object]:
    """Discover and load project-level agents.

    Scans ``<project_root>/.writer/agents/*.md`` (NOT a subdirectory
    per-agent — agents are flat ``.md`` files at the top level,
    mirroring Claude Code's ``.claude/agents/`` layout). Hidden files
    (``_draft`` / ``.hidden``) and files without valid YAML
    frontmatter are skipped silently (with a WARNING).
    """

    agents: list[object] = []
    agents_dir = (project_root / ".writer" / "agents").resolve()
    if not agents_dir.is_dir():
        return agents

    try:
        candidates = sorted(p for p in agents_dir.iterdir() if p.is_file())
    except OSError as exc:
        log.warning(
            "Cannot enumerate project agents at %s: %s; "
            "continuing without project layer",
            agents_dir,
            exc,
        )
        return agents

    for path in candidates:
        basename = path.name
        if basename.startswith("_") or basename.startswith("."):
            log.debug("Skipping non-public project agent: %s", path)
            continue
        if not basename.endswith(".md"):
            log.debug("Skipping non-md project agent file: %s", path)
            continue
        agent = _parse_agent_file(path)
        if agent is not None:
            agents.append(agent)
    return agents


def discover_shipped_agents() -> list[object]:
    """Discover the 4 built-in agents shipped at
    ``writer.agents._shipped/<name>.md``.

    Uses ``importlib.resources.files()`` so the loader works regardless
    of whether the package is installed from a wheel, an sdist, or
    imported directly from a source checkout.
    """

    agents: list[object] = []
    try:
        # Python 3.12+: ``files()`` returns a ``Traversable``.
        root = importlib.resources.files("writer.agents._shipped")
    except Exception as exc:  # noqa: BLE001 — packaging environments vary
        log.warning(
            "Cannot locate shipped agents package: %s: %s; "
            "shipped layer will be empty",
            type(exc).__name__,
            exc,
        )
        return agents

    try:
        file_iter = sorted(
            (p for p in root.iterdir() if p.name.endswith(".md")),
            key=lambda p: p.name,
        )
    except (OSError, NotImplementedError) as exc:
        log.warning(
            "Cannot iterate shipped agents: %s: %s; "
            "shipped layer will be empty",
            type(exc).__name__,
            exc,
        )
        return agents

    for traversable in file_iter:
        agent = _parse_traversable_agent(traversable)
        if agent is not None:
            agents.append(agent)
    return agents


def discover_entry_point_agents() -> list[object]:
    """Discover agents registered via Python entry points.

    Plugins register agents by adding an entry to
    ``[project.entry-points."writer.agents"]`` in their
    ``pyproject.toml``:

    .. code-block:: toml

       [project.entry-points."writer.agents"]
       my_agent = "my_pkg.my_mod:MyAgent"

    Each entry point may resolve to:

    * an :class:`Agent` class — instantiated with no arguments;
    * a pre-built :class:`Agent` instance — used as-is.

    Anything that fails to resolve (missing distribution, import
    error, bad attribute, schema invalid) is logged at WARNING and
    skipped so a broken plugin never blocks the REPL from starting.
    """

    from writer.agents.protocol import Agent  # noqa: PLC0415
    from writer.agents.registry import AgentRegistryError, _validate  # noqa: PLC0415

    discovered: list[object] = []
    try:
        entries = metadata.entry_points(group="writer.agents")
    except Exception:  # noqa: BLE001
        log.warning(
            "Agent entry_points discovery failed; continuing without plugins"
        )
        return discovered

    for entry in entries:
        try:
            target = entry.load()
        except Exception:  # noqa: BLE001
            log.warning(
                "Failed to import agent entry point %s=%s; skipping",
                entry.name,
                entry.value,
            )
            continue

        try:
            if isinstance(target, type):
                instance: object = target()
            elif isinstance(target, Agent):
                instance = target
            else:
                log.warning(
                    "Agent entry point %s did not resolve to an Agent "
                    "(got %s); skipping",
                    entry.name,
                    type(target).__name__,
                )
                continue
        except Exception:  # noqa: BLE001
            log.warning(
                "Agent entry point %s constructor raised; skipping",
                entry.name,
            )
            continue

        try:
            _validate(instance)
        except AgentRegistryError as exc:
            log.warning("Agent entry point %s rejected: %s", entry.name, exc)
            continue

        discovered.append(instance)
    return discovered


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def parse_agent_file(path: Path) -> object:
    """Parse one agent ``.md`` file on the regular filesystem.

    Exposed as a top-level helper so tests can call it directly. Raises
    :class:`writer.agents.registry.AgentRegistryError` on schema
    errors (missing required keys, empty body, bad name).
    """

    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        msg = f"cannot read agent file at {path}: {exc}"
        raise AgentRegistryError(msg) from exc

    return _build_agent_from_text(text, root=path.resolve())


def _parse_agent_file(path: Path) -> object | None:
    """Wrapper that logs on failure (used by the discovery loop)."""

    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    try:
        return parse_agent_file(path)
    except AgentRegistryError as exc:
        log.warning("Agent file at %s rejected: %s; skipping", path, exc)
        return None


def _parse_traversable_agent(traversable) -> object | None:
    """Parse one shipped agent ``.md`` accessed via ``importlib.resources``.

    ``importlib.resources`` returns ``Traversable`` objects (not real
    paths). We read via ``.read_text(encoding='utf-8')`` and use the
    stringified path as the agent's ``root``.
    """

    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    try:
        text = traversable.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning(
            "Cannot read shipped agent at %s: %s; skipping",
            traversable,
            exc,
        )
        return None

    try:
        return _build_agent_from_text(text, root=Path(str(traversable)))
    except AgentRegistryError as exc:
        log.warning(
            "Shipped agent at %s rejected: %s; skipping",
            traversable,
            exc,
        )
        return None


def _build_agent_from_text(text: str, *, root: Path) -> object:
    """Build an :class:`Agent` from raw ``.md`` text + root path.

    Raises :class:`AgentRegistryError` on any schema violation.
    """

    from writer.agents.protocol import Agent  # noqa: PLC0415
    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    parsed = _parse_frontmatter_and_body(text)
    if parsed is None:
        msg = f"agent file at {root} has invalid frontmatter envelope"
        raise AgentRegistryError(msg)
    front, body = parsed

    meta = _validate_frontmatter(front, source=str(root))
    return Agent(
        name=meta["name"],
        description=meta["description"],
        genre=meta["genre"],
        body=body.rstrip("\n"),
        tools_allowlist=meta["tools_allowlist"],
        root=root,
    )


def _parse_frontmatter_and_body(text: str) -> tuple[str, str] | None:
    """Extract YAML frontmatter and Markdown body from an agent file."""

    match = _FRONTMATTER_PATTERN.match(text)
    if match is None:
        return None
    return match["front"], match["body"]


def _validate_frontmatter(front_str: str, *, source: str) -> dict:
    """Parse + validate the YAML frontmatter. Raises :class:`AgentRegistryError`."""

    import yaml  # local import: top-level yaml import is heavy

    from writer.agents.registry import AgentRegistryError  # noqa: PLC0415

    try:
        data = yaml.safe_load(front_str)
    except yaml.YAMLError as exc:
        msg = f"YAML parse error in {source}: {exc}"
        raise AgentRegistryError(msg) from exc

    if not isinstance(data, dict):
        msg = f"frontmatter in {source} must be a mapping; got {type(data).__name__}"
        raise AgentRegistryError(msg)

    name = data.get("name")
    if not isinstance(name, str) or not name.strip():
        msg = f"frontmatter in {source}: `name` must be a non-empty string"
        raise AgentRegistryError(msg)

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        msg = f"frontmatter in {source}: `description` must be a non-empty string"
        raise AgentRegistryError(msg)
    description = description.strip()
    if not (50 <= len(description) <= 500):
        msg = (
            f"frontmatter in {source}: `description` length must be 50-500 "
            f"chars; got {len(description)}"
        )
        raise AgentRegistryError(msg)

    genre = data.get("genre")
    if not isinstance(genre, str) or not genre.strip():
        msg = f"frontmatter in {source}: `genre` must be a non-empty string"
        raise AgentRegistryError(msg)

    raw_tools = data.get("tools", [])
    if raw_tools is None:
        raw_tools = []
    if not isinstance(raw_tools, list) or not all(
        isinstance(t, str) for t in raw_tools
    ):
        msg = f"frontmatter in {source}: `tools` must be a list of strings"
        raise AgentRegistryError(msg)

    return {
        "name": name.strip(),
        "description": description,
        "genre": genre.strip(),
        "tools_allowlist": tuple(raw_tools),
    }


__all__ = [
    "discover_agents",
    "discover_shipped_agents",
    "discover_entry_point_agents",
    "parse_agent_file",
]
