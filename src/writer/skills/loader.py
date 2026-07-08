"""Project-level skill discovery and loading.

Mirrors :func:`writer.skills.registry.discover_entry_point_skills` but
scans the filesystem instead of Python entry points. Used by
:func:`writer.skills.registry.built_skill_registry` to layer project
skills on top of the built-in defaults.

Layout expected under ``<project_root>/.writer/skills/``:

* ``<basename>.py`` — required. Defines a single ``Skill`` subclass or
  exposes a pre-built ``Skill`` instance as a top-level variable.
* ``<basename>.md`` — optional. UTF-8 Markdown whose content is copied
  verbatim (trailing newline stripped) into the skill's
  ``extra_instructions`` field.

Failure modes (syntax error, missing ``Skill`` class, validation
error) are logged at WARNING and skipped — a single broken project
skill MUST NOT prevent other project skills from loading and MUST NOT
prevent the REPL from starting. This mirrors the
:func:`discover_entry_point_skills` policy verbatim.
"""

from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path
from typing import TYPE_CHECKING

from writer.skills.errors import SkillError
from writer.skills.protocol import Skill

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


# Required Skill attributes used by the structural subclass check in
# ``_extract_skill``. Mirrors the four non-method members of the
# :class:`writer.skills.Skill` Protocol.
_REQUIRED_SKILL_ATTRS: tuple[str, ...] = (
    "command",
    "description",
    "requires_states",
    "extra_instructions",
    "run",
)


def discover_project_skills(project_root: Path) -> list[Skill]:
    """Discover and load project-level skills from
    ``<project_root>/.writer/skills/``.

    Returns a list of validated ``Skill`` instances. The order matches
    the on-disk order of the ``.py`` files (sorted by basename for
    determinism — alphabetical on bytes). Failures are logged at
    WARNING and skipped.

    The function NEVER raises for a per-file failure. The only
    exceptions that can escape are programmer errors (e.g. ``project_root``
    is not a ``Path``); filesystem-level errors like permission denied
    on the skills directory itself are caught and treated as "no
    project skills" (the function returns ``[]``).
    """

    skills: list[Skill] = []
    skills_dir = (project_root / ".writer" / "skills").resolve()
    if not skills_dir.is_dir():
        return skills

    try:
        candidates = sorted(skills_dir.glob("*.py"))
    except OSError as exc:
        log.warning(
            "Cannot enumerate project skills at %s: %s; continuing without",
            skills_dir,
            exc,
        )
        return skills

    for path in candidates:
        basename = path.stem
        if basename.startswith("_") or basename.startswith("."):
            log.debug("Skipping non-public project skill file: %s", path)
            continue
        skill = _load_one(path, basename, skills_dir)
        if skill is not None:
            skills.append(skill)
    return skills


def _load_one(path: Path, basename: str, skills_dir: Path) -> Skill | None:
    """Load a single ``<basename>.py`` and read its companion ``.md``.

    Returns ``None`` and logs a WARNING on any failure. Returns the
    loaded ``Skill`` instance (with ``extra_instructions`` populated
    from the companion Markdown if present) on success.
    """

    module_name = f"writer_user_skill_{basename}"
    try:
        spec = importlib.util.spec_from_file_location(module_name, path)
    except (OSError, ValueError) as exc:
        log.warning(
            "Cannot build import spec for project skill %s: %s; skipping",
            path,
            exc,
        )
        return None
    if spec is None or spec.loader is None:
        log.warning(
            "Could not resolve loader for project skill %s; skipping", path
        )
        return None

    module = importlib.util.module_from_spec(spec)
    try:
        # Register in sys.modules so the loaded module can resolve its
        # own relative imports if it uses any. Without this, a project
        # skill that does ``from .utils import foo`` would fail with
        # ImportError even though the file loaded.
        sys.modules[module_name] = module
        spec.loader.exec_module(module)
    except SyntaxError as exc:
        log.warning(
            "SyntaxError in project skill %s (line %d): %s; skipping",
            path,
            exc.lineno or 0,
            exc.msg,
        )
        sys.modules.pop(module_name, None)
        return None
    except Exception as exc:  # noqa: BLE001 — project code is user-controlled
        log.warning(
            "Failed to import project skill %s: %s: %s; skipping",
            path,
            type(exc).__name__,
            exc,
        )
        sys.modules.pop(module_name, None)
        return None

    instance = _extract_skill(module, path)
    if instance is None:
        sys.modules.pop(module_name, None)
        return None

    md_path = skills_dir / f"{basename}.md"
    if md_path.is_file():
        try:
            text = md_path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            log.warning(
                "Cannot read companion Markdown %s: %s; "
                "leaving extra_instructions empty",
                md_path,
                exc,
            )
        else:
            instance.extra_instructions = text.rstrip("\n")

    return instance


def _extract_skill(module: object, path: Path) -> Skill | None:
    """Find one ``Skill`` instance inside ``module``.

    Lookup order:

    1. A top-level variable named after the file basename (case-sensitive
       Python identifier) that is a ``Skill`` instance — used as-is.
    2. A top-level ``Skill`` subclass (any name) — instantiated with no
       arguments.
    3. None of the above — log a WARNING and return ``None``.

    The function deliberately rejects modules that define multiple
    candidate classes to keep "one file = one skill" the only valid
    shape; users who want more can split their code into multiple
    ``<basename>.py`` files.
    """

    basename = path.stem

    # 1. Top-level variable matching the file basename.
    direct = getattr(module, basename, None)
    if isinstance(direct, Skill):
        if _safe_validate(direct, path):
            return direct
        return None

    # 2. Scan all top-level Skill subclasses.
    candidates: list[type] = []
    for attr_name in dir(module):
        if attr_name.startswith("_"):
            continue
        attr = getattr(module, attr_name, None)
        if not isinstance(attr, type) or attr is Skill:
            continue
        # ``Skill`` is a runtime_checkable Protocol with non-method
        # members (command/description/...), so mypy refuses plain
        # ``issubclass``. The structural check below is the documented
        # Protocol-with-members pattern: every required attribute must
        # exist on the class. This is the same trick LangChain uses
        # for its own runtime_checkable protocols.
        if not all(hasattr(attr, name) for name in _REQUIRED_SKILL_ATTRS):
            continue
        # Exclude abstract subclasses (mirrors the spirit of the
        # ``issubclass`` branch we used to write).
        if getattr(attr, "__abstractmethods__", None):
            continue
        candidates.append(attr)

    if not candidates:
        log.warning(
            "Project skill %s exposes no Skill subclass or instance; "
            "expected a class derived from writer.skills.Skill "
            "(or a top-level %r variable holding an instance); skipping",
            path,
            basename,
        )
        return None

    if len(candidates) > 1:
        log.warning(
            "Project skill %s defines multiple Skill subclasses (%s); "
            "expected exactly one; skipping",
            path,
            ", ".join(c.__name__ for c in candidates),
        )
        return None

    klass = candidates[0]
    try:
        instance = klass()
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Project skill class %s in %s raised in no-arg __init__: %s: %s; "
            "skipping",
            klass.__name__,
            path,
            type(exc).__name__,
            exc,
        )
        return None

    if not _safe_validate(instance, path):
        return None
    return instance


def _safe_validate(skill: Skill, path: Path) -> bool:
    """Run :func:`writer.skills.registry._validate_skill`, log + suppress errors.

    Returns ``True`` when the skill passes validation, ``False`` otherwise.
    """

    # Local import to avoid a circular import (registry → skills,
    # loader → skills). The function is stable across releases.
    from writer.skills.registry import _validate_skill  # noqa: PLC0415

    try:
        _validate_skill(skill)
    except SkillError as exc:
        log.warning(
            "Project skill in %s rejected by validator: %s; skipping",
            path,
            exc,
        )
        return False
    return True


__all__ = ["discover_project_skills"]
