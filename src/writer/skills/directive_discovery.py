"""Project-level and shipped-directive discovery.

Public surface (per chg-markdown-skills):

* :func:`discover_directives` — scan a project's
  ``<project_root>/.writer/skills/*/SKILL.md`` directories and load
  every well-formed ``SkillDirective``.
* :func:`discover_shipped_directives` — list the 4 built-in directives
  shipped at ``src/writer/skills/_shipped/`` via ``importlib.resources``.
* :func:`discover_entry_point_directives` — entry-point plugin hook
  (mirrors the prior ``discover_entry_point_skills`` policy).

All failures are logged at WARNING and skipped — a single broken
directive MUST NOT prevent other directives from loading and MUST NOT
prevent the REPL from starting. This mirrors the prior
``discover_entry_point_skills`` behaviour verbatim.
"""

from __future__ import annotations

import importlib.resources
import importlib.util
import logging
import re
import sys
from importlib import metadata
from pathlib import Path
from typing import TYPE_CHECKING

from writer.skills.errors import SkillError
from writer.skills.protocol import SkillDirective

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


#: Frontmatter pattern: ``---\n<yaml>---\n<body>``. We require both
#: delimiters to be present (the file MUST be a complete YAML doc).
#: Multiline frontmatter is supported; the closing ``---`` MUST be on
#: its own line.
_FRONTMATTER_PATTERN = re.compile(
    r"\A---\s*\n(?P<front>.*?)\n---\s*\n(?P<body>.*)\Z",
    re.DOTALL,
)

#: ``@reference path/to/file.md`` references inside a SKILL.md body.
#: Captures the relative path (no whitespace) between ``@reference``
#: and either whitespace or end-of-line.
_REFERENCE_PATTERN = re.compile(r"@reference\s+(?P<path>[^\s]+)")


def discover_directives(project_root: Path) -> list[SkillDirective]:
    """Discover and load project-level directives.

    Scans ``<project_root>/.writer/skills/*/SKILL.md``, returning a
    list of validated :class:`SkillDirective` instances sorted by
    command for deterministic ordering.

    Hidden directories (``_draft`` / ``.hidden``) and entries without
    a ``SKILL.md`` file are skipped silently.
    """

    directives: list[SkillDirective] = []
    skills_dir = (project_root / ".writer" / "skills").resolve()
    if not skills_dir.is_dir():
        return directives

    try:
        candidates = sorted(p for p in skills_dir.iterdir() if p.is_dir())
    except OSError as exc:
        log.warning(
            "Cannot enumerate project directives at %s: %s; "
            "continuing without project layer",
            skills_dir,
            exc,
        )
        return directives

    for sub in candidates:
        basename = sub.name
        if basename.startswith("_") or basename.startswith("."):
            log.debug("Skipping non-public project directive: %s", sub)
            continue
        skill_md = sub / "SKILL.md"
        if not skill_md.is_file():
            log.debug("Skipping directory without SKILL.md: %s", sub)
            continue
        directive = _parse_skill_md(skill_md)
        if directive is not None:
            directives.append(directive)
    return directives


def discover_shipped_directives() -> list[SkillDirective]:
    """Discover the 4 built-in directives shipped at
    ``writer.skills._shipped/<command>/SKILL.md``.

    Uses ``importlib.resources.files()`` so the loader works regardless
    of whether the package is installed from a wheel, an sdist, or
    imported directly from a source checkout.
    """

    directives: list[SkillDirective] = []
    try:
        # Python 3.12+: ``files()`` returns a ``Traversable``.
        root = importlib.resources.files("writer.skills._shipped")
    except Exception as exc:  # noqa: BLE001 — packaging environments vary
        log.warning(
            "Cannot locate shipped directives package: %s: %s; "
            "shipped layer will be empty",
            type(exc).__name__,
            exc,
        )
        return directives

    try:
        sub_iter = sorted(p for p in root.iterdir() if p.is_dir())
    except (OSError, NotImplementedError) as exc:
        log.warning(
            "Cannot iterate shipped directives: %s: %s; "
            "shipped layer will be empty",
            type(exc).__name__,
            exc,
        )
        return directives

    for sub in sub_iter:
        skill_md = sub / "SKILL.md"
        directive = _parse_traversable_skill_md(skill_md)
        if directive is not None:
            directives.append(directive)
    return directives


def discover_entry_point_directives() -> list[SkillDirective]:
    """Discover directives registered via Python entry points.

    Plugins register directives by adding an entry to
    ``[project.entry-points."writer.directives"]`` in their
    ``pyproject.toml``:

    .. code-block:: toml

       [project.entry-points."writer.directives"]
       my_directive = "my_pkg.my_mod:MyDirective"

    Each entry point may resolve to:

    * a :class:`SkillDirective` class — instantiated with no arguments;
    * a pre-built :class:`SkillDirective` instance — used as-is.

    Anything that fails to resolve (missing distribution, import
    error, bad attribute, schema invalid) is logged at WARNING and
    skipped so a broken plugin never blocks the REPL from starting.
    """

    discovered: list[SkillDirective] = []
    try:
        entries = metadata.entry_points(group="writer.directives")
    except Exception:  # noqa: BLE001
        log.warning(
            "Directive entry_points discovery failed; continuing without plugins"
        )
        return discovered

    for entry in entries:
        try:
            target = entry.load()
        except Exception:  # noqa: BLE001
            log.warning(
                "Failed to import directive entry point %s=%s; skipping",
                entry.name,
                entry.value,
            )
            continue

        try:
            if isinstance(target, type):
                instance = target()
            elif isinstance(target, SkillDirective):
                instance = target
            else:
                log.warning(
                    "Directive entry point %s did not resolve to a SkillDirective "
                    "(got %s); skipping",
                    entry.name,
                    type(target).__name__,
                )
                continue
        except Exception:  # noqa: BLE001
            log.warning(
                "Directive entry point %s constructor raised; skipping",
                entry.name,
            )
            continue

        try:
            _validate(instance)
        except SkillError as exc:
            log.warning("Directive entry point %s rejected: %s", entry.name, exc)
            continue

        discovered.append(instance)
    return discovered


# ---------------------------------------------------------------------------
# Parsing helpers
# ---------------------------------------------------------------------------


def _parse_skill_md(skill_md_path: Path) -> SkillDirective | None:
    """Parse one ``SKILL.md`` file on the regular filesystem."""

    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning(
            "Cannot read SKILL.md at %s: %s; skipping",
            skill_md_path,
            exc,
        )
        return None

    parsed = _parse_frontmatter_and_body(text)
    if parsed is None:
        log.warning(
            "SKILL.md at %s has invalid frontmatter; skipping",
            skill_md_path,
        )
        return None
    front, body = parsed

    try:
        meta = _validate_frontmatter(front)
    except SkillError as exc:
        log.warning("SKILL.md at %s rejected: %s; skipping", skill_md_path, exc)
        return None

    references = _load_references(skill_md_path.parent)
    scripts = _list_scripts(skill_md_path.parent)

    return SkillDirective(
        command=meta["command"],
        description=meta["description"],
        requires_states=meta["requires_states"],
        body=body.rstrip("\n"),
        references=references,
        scripts=scripts,
        root=skill_md_path.parent.resolve(),
    )


def _parse_traversable_skill_md(traversable) -> SkillDirective | None:
    """Parse one shipped SKILL.md accessed via ``importlib.resources``.

    ``importlib.resources`` returns ``Traversable`` objects (not real
    paths). We read via ``.read_text(encoding='utf-8')`` and pass the
    parent ``Traversable`` (instead of a ``Path``) to the references
    loader so the same code works for both regular filesystem and
    package resources.
    """

    try:
        text = traversable.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        log.warning(
            "Cannot read shipped SKILL.md at %s: %s; skipping",
            traversable,
            exc,
        )
        return None

    parsed = _parse_frontmatter_and_body(text)
    if parsed is None:
        log.warning(
            "Shipped SKILL.md at %s has invalid frontmatter; skipping",
            traversable,
        )
        return None
    front, body = parsed

    try:
        meta = _validate_frontmatter(front)
    except SkillError as exc:
        log.warning(
            "Shipped SKILL.md at %s rejected: %s; skipping",
            traversable,
            exc,
        )
        return None

    references = _load_traversable_references(traversable.parent)
    scripts = _list_traversable_scripts(traversable.parent)

    # For shipped directives, ``root`` is a Traversable — we keep it as
    # the stringified path so downstream code can still log it. The
    # engine does NOT execute scripts for shipped directives (they're
    # only seeded as reference templates).
    return SkillDirective(
        command=meta["command"],
        description=meta["description"],
        requires_states=meta["requires_states"],
        body=body.rstrip("\n"),
        references=references,
        scripts=scripts,
        root=Path(str(traversable.parent)),
    )


def _parse_frontmatter_and_body(text: str) -> tuple[str, str] | None:
    """Extract YAML frontmatter and Markdown body from a SKILL.md file.

    Returns ``(frontmatter_str, body_str)`` or ``None`` when the file
    has no proper ``---\\n...\\n---\\n`` envelope.
    """

    match = _FRONTMATTER_PATTERN.match(text)
    if match is None:
        return None
    return match["front"], match["body"]


def _validate_frontmatter(front_str: str) -> dict:
    """Parse + validate the YAML frontmatter. Raises ``SkillError``."""

    import yaml  # local import: top-level yaml import is heavy

    try:
        data = yaml.safe_load(front_str)
    except yaml.YAMLError as exc:
        msg = f"YAML parse error: {exc}"
        raise SkillError(msg) from exc

    if not isinstance(data, dict):
        msg = "frontmatter must be a mapping"
        raise SkillError(msg)

    command = data.get("command")
    if not isinstance(command, str) or not command.startswith("/"):
        msg = f"command must be a non-empty string starting with '/'; got {command!r}"
        raise SkillError(msg)

    description = data.get("description")
    if not isinstance(description, str) or not description.strip():
        msg = "description must be a non-empty string"
        raise SkillError(msg)

    raw_states = data.get("requires_states", [])
    if isinstance(raw_states, str):
        raw_states = [raw_states]
    if not isinstance(raw_states, list) or not raw_states:
        msg = "requires_states must be a non-empty list"
        raise SkillError(msg)

    # Resolve requires_states strings to ProjectState enum members.
    # ProjectState is a StrEnum where the value is the canonical S0..S5
    # string and the NAME is the human-readable identifier. We accept
    # either form so SKILL.md frontmatter can use whichever is clearer:
    #   ``requires_states: [INITIALIZED, HAS_OUTLINE]``  ← name form
    #   ``requires_states: [S1, S2]``                    ← value form
    # Local import: avoid forcing project.state on every skills import.
    from writer.project.state import ProjectState  # noqa: PLC0415

    # Build a name → ProjectState map once for the name-form lookup.
    name_to_state = {member.name: member for member in ProjectState}

    resolved_states: set = set()
    for raw in raw_states:
        if not isinstance(raw, str):
            msg = f"requires_states entries must be strings; got {type(raw).__name__}"
            raise SkillError(msg)
        if raw in name_to_state:
            resolved_states.add(name_to_state[raw])
            continue
        try:
            resolved_states.add(ProjectState(raw))
        except ValueError as exc:
            valid = sorted(s for s in ProjectState)
            msg = (
                f"requires_states entry {raw!r} is not a valid ProjectState; "
                f"expected one of {valid} (by name) or their S0..S5 values"
            )
            raise SkillError(msg) from exc

    return {
        "command": command,
        "description": description.strip(),
        "requires_states": frozenset(resolved_states),
    }


def _validate(directive: SkillDirective) -> None:
    """Light validation for entry-point / programmatically-built directives."""

    if not isinstance(directive.command, str) or not directive.command.startswith("/"):
        msg = f"directive command must start with '/'; got {directive.command!r}"
        raise SkillError(msg)
    if not isinstance(directive.description, str) or not directive.description.strip():
        msg = "directive description must be a non-empty string"
        raise SkillError(msg)
    if not isinstance(directive.requires_states, frozenset) or not directive.requires_states:
        msg = "directive requires_states must be a non-empty frozenset"
        raise SkillError(msg)
    if not isinstance(directive.body, str):
        msg = "directive body must be a string"
        raise SkillError(msg)


def _load_references(skill_dir: Path) -> dict[str, str]:
    """Load every ``*.md`` under ``<skill_dir>/references/``.

    Returns ``{relpath: content}`` keyed by relative path. Non-md files
    are skipped silently. Missing ``references/`` directory → ``{}``.
    """

    refs_dir = skill_dir / "references"
    if not refs_dir.is_dir():
        return {}
    out: dict[str, str] = {}
    for path in sorted(refs_dir.rglob("*.md")):
        try:
            rel = path.relative_to(refs_dir).as_posix()
        except ValueError:
            continue
        try:
            out[rel] = path.read_text(encoding="utf-8").rstrip("\n")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning(
                "Cannot read reference %s in %s: %s; skipping",
                path,
                skill_dir,
                exc,
            )
    return out


def _list_scripts(skill_dir: Path) -> list[str]:
    """List relative paths of files under ``<skill_dir>/scripts/``."""

    scripts_dir = skill_dir / "scripts"
    if not scripts_dir.is_dir():
        return []
    out: list[str] = []
    for path in sorted(scripts_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(skill_dir).as_posix()
        except ValueError:
            continue
        out.append(rel)
    return out


def _load_traversable_references(parent_traversable) -> dict[str, str]:
    """Load references from a ``Traversable`` (importlib.resources)."""

    refs_dir = parent_traversable / "references"
    try:
        if not refs_dir.is_dir():
            return {}
    except (OSError, NotImplementedError):
        return {}

    out: dict[str, str] = {}
    try:
        candidates = sorted(p for p in refs_dir.rglob("*.md"))
    except (OSError, NotImplementedError) as exc:
        log.warning("Cannot iterate references at %s: %s; skipping", refs_dir, exc)
        return out

    for path in candidates:
        try:
            rel = path.relative_to(refs_dir).as_posix()
        except ValueError:
            continue
        try:
            out[rel] = path.read_text(encoding="utf-8").rstrip("\n")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning(
                "Cannot read shipped reference %s: %s; skipping", path, exc
            )
    return out


def _list_traversable_scripts(parent_traversable) -> list[str]:
    """List scripts from a ``Traversable`` (importlib.resources)."""

    scripts_dir = parent_traversable / "scripts"
    try:
        if not scripts_dir.is_dir():
            return []
    except (OSError, NotImplementedError):
        return []

    out: list[str] = []
    try:
        candidates = sorted(scripts_dir.rglob("*"))
    except (OSError, NotImplementedError) as exc:
        log.warning("Cannot iterate scripts at %s: %s; skipping", scripts_dir, exc)
        return out

    for path in candidates:
        try:
            if not path.is_file():
                continue
        except (OSError, NotImplementedError):
            continue
        try:
            rel = path.relative_to(parent_traversable).as_posix()
        except ValueError:
            continue
        out.append(rel)
    return out


def resolve_references(body: str, references: dict[str, str]) -> list[tuple[str, str]]:
    """Resolve ``@reference path/to/file.md`` mentions in a directive body.

    Returns ``[(relpath, content)]`` for every reference that exists in
    the directive's ``references`` dict. Unknown references are silently
    skipped — the engine logs them as a WARNING and continues.

    Path normalization: ``references`` keys are stored relative to the
    ``references/`` subdirectory (e.g. ``template.md``), but SKILL.md
    bodies often write the full path (``references/template.md``). The
    ``references/`` prefix is stripped on lookup so authors can use
    either form.

    Order: the order in which the references appear in the body.
    Deduplication: a reference mentioned multiple times appears once.
    """

    if not references:
        return []

    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for match in _REFERENCE_PATTERN.finditer(body):
        relpath = match["path"]
        # Allow both ``@reference template.md`` and
        # ``@reference references/template.md`` to look up the same
        # ``template.md`` key.
        normalized = (
            relpath[len("references/") :]
            if relpath.startswith("references/")
            else relpath
        )
        if normalized in seen:
            continue
        seen.add(normalized)
        content = references.get(normalized)
        if content is None:
            log.warning(
                "Directive body references %r but it is not in references; skipping",
                relpath,
            )
            continue
        out.append((normalized, content))
    return out


__all__ = [
    "discover_directives",
    "discover_shipped_directives",
    "discover_entry_point_directives",
    "resolve_references",
]