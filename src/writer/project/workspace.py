"""Novel project workspace scaffolding.

``create_workspace`` materialises the on-disk layout for a novel project.
The base layout (``manuscript / outline / characters / world / notes`` +
``AGENT.md / README.md`` + one stub per subdirectory) is **genre-agnostic**;
genre-specific extras (history ``史实/``, xuanhuan ``伏笔/``, romance
``人设/``) are layered on top by :func:`_genre_scaffolding` and merged into
the returned ``created_files`` list.

When ``with_writer_meta=True`` (the path used by
:func:`create_new_workspace`, i.e. ``writer new``),
:func:`_writer_meta_scaffolding` also creates ``<root>/.writer/`` with
three sub-areas: a ``skills/`` directory mirroring the four built-in
skills, an empty ``agents/`` directory, and a ``config`` env-style file.

Genre values are normalised by :func:`_normalize_genre` — Chinese labels
(``历史 / 言情 / 玄幻``) and English short forms (``history / romance /
xuanhuan``) map onto the same key. Anything else falls back to
``"other"``, which produces the original default layout and no extras.

Backward compatibility is preserved: ``create_workspace(name, base_dir)``
without an explicit ``genre`` keyword behaves exactly as before (other
fallback). See ``tests/test_workspace.py`` for the contracts.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from writer.project.genre import format_genre_line, normalize_genres, primary_genre
from writer.project.state import ProjectState, render_agent_file

_WRITER_CONFIG_TEMPLATE = """\
# 项目级 LLM 配置（优先级高于 .env）
WRITER_MODEL=gpt-4o-mini
WRITER_API_KEY=
WRITER_BASE_URL=https://api.openai.com/v1
WRITER_TEMPERATURE=0.7
"""


@dataclass(frozen=True)
class NovelWorkspace:
    root: Path
    created_files: list[Path]


# Genre whitelist — must stay in sync with the CLI prompt options.
# English short forms accepted as aliases (lower-case, strip-tolerant).
_GENRE_ALIASES: dict[str, str] = {
    "历史": "历史",
    "history": "历史",
    "historical": "历史",
    "言情": "言情",
    "romance": "言情",
    "玄幻": "玄幻",
    "xuanhuan": "玄幻",
    "fantasy": "玄幻",
    "other": "other",
    "其他": "other",
    "其它": "other",
}


def _normalize_genre(genre: str) -> str:
    """Return the canonical genre key for the input.

    Any value not in the alias table — including custom user strings like
    ``"都市悬疑"`` or ``"科幻"`` — is returned as ``"other"``. Empty /
    whitespace input is also treated as ``"other"``.
    """
    key = (genre or "").strip().lower()
    return _GENRE_ALIASES.get(key, "other")


def create_workspace(
    name: str,
    base_dir: Path,
    *,
    force: bool = False,
    genre: str = "other",
    genres: list[str] | None = None,
    with_ideas_dir: bool = False,
    with_writer_meta: bool = False,
) -> NovelWorkspace:
    project_name = _normalize_name(name)
    genre_list = normalize_genres(genres if genres is not None else [genre])
    canonical_genre = primary_genre(genre_list)
    root = base_dir / project_name

    if root.exists() and not force:
        msg = (
            f"项目目录已存在: {root}。"
            f"如要覆盖请重新执行 `writer init {project_name} --force`，"
            f"或先手动删除/重命名该目录。"
        )
        raise FileExistsError(msg)

    directories = [
        root / "manuscript",
        root / "outline",
        root / "characters",
        root / "world",
        root / "notes",
    ]
    if with_ideas_dir:
        directories.append(root / "创意")
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    files = {
        root / "AGENT.md": render_agent_file(
            project_name,
            ProjectState.INITIALIZED,
            genre=format_genre_line(genre_list) or canonical_genre,
        ),
        root / "README.md": f"# {project_name}\n\n长篇小说项目工作区。\n",
        root / "outline" / "premise.md": "# 一句话创意\n\n",
        root / "outline" / "volume-plan.md": "# 分卷规划\n\n",
        root / "characters" / "main.md": "# 主要人物\n\n",
        root / "world" / "setting.md": "# 世界观设定\n\n",
        root / "notes" / "todo.md": "# 待办\n\n",
    }

    created_files: list[Path] = []
    for path, content in files.items():
        if force or not path.exists():
            path.write_text(content, encoding="utf-8")
            created_files.append(path)

    if with_ideas_dir:
        ideas_stub = root / "创意" / "README.md"
        if force or not ideas_stub.exists():
            ideas_stub.write_text("# 创意库\n\n存放故事创意、灵感与核心设定。\n", encoding="utf-8")
            created_files.append(ideas_stub)

    # Genre-specific scaffolding layered on top of the base layout.
    created_files.extend(_genre_scaffolding(root, canonical_genre))

    if with_writer_meta:
        created_files.extend(_writer_meta_scaffolding(root, force=force))

    return NovelWorkspace(root=root, created_files=created_files)


def create_new_workspace(
    name: str,
    base_dir: Path,
    *,
    force: bool = False,
    genres: list[str] | None = None,
) -> NovelWorkspace:
    """Create a novel project with ``创意/`` and ``.writer/`` metadata."""

    return create_workspace(
        name,
        base_dir,
        force=force,
        genres=genres,
        with_ideas_dir=True,
        with_writer_meta=True,
    )


def _writer_meta_scaffolding(root: Path, *, force: bool = False) -> list[Path]:
    writer_root = root / ".writer"
    targets = {
        writer_root / "skills" / ".gitkeep": "",
        writer_root / "agents" / ".gitkeep": "",
        writer_root / "config": _WRITER_CONFIG_TEMPLATE,
    }
    created: list[Path] = []
    for path, content in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if force or not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(path)

    created.extend(_seed_directives(writer_root, force=force))
    return created


def _seed_directives(
    writer_root: Path, *, force: bool = False
) -> list[Path]:
    """Copy the 4 shipped SKILL.md directive packages into the project.

    Each shipped directive lives under
    ``writer.skills._shipped/<command>/`` (loaded via
    :mod:`importlib.resources`). This helper copies the whole
    directory tree — ``SKILL.md`` + ``references/*.md`` (and any
    future ``scripts/*.py``) — into
    ``<writer_root>/skills/<command>/``.

    After copying, the project's directory contains the same files as
    the shipped source. The discovery layer treats shipped and
    user-added directives identically — the user is free to edit,
    delete, or extend.

    Per-directive failures are logged at WARNING and skipped (so a
    broken shipped copy does not block the rest). Files that already
    exist on disk are left untouched unless ``force=True``.

    Called by :func:`_writer_meta_scaffolding` only when
    ``with_writer_meta=True`` (the ``create_new_workspace`` path).
    The low-level :func:`create_workspace` does NOT seed directives.
    """

    skills_dir = writer_root / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Local import: keeps the workspace module free of a top-level
    # writer.skills dependency (avoids any future circular import
    # risk).
    try:
        import importlib.resources as _resources
    except ImportError:  # pragma: no cover — Python 3.12+ has it
        return []

    created: list[Path] = []
    try:
        shipped_root = _resources.files("writer.skills._shipped")
    except Exception as exc:  # noqa: BLE001
        import logging

        logging.getLogger(__name__).warning(
            "Cannot locate shipped directives package: %s: %s; "
            "directive seeding skipped",
            type(exc).__name__,
            exc,
        )
        return []

    try:
        sub_iter = sorted(
            (p for p in shipped_root.iterdir() if p.is_dir()),
            key=lambda p: p.name,
        )
    except (OSError, NotImplementedError) as exc:
        import logging

        logging.getLogger(__name__).warning(
            "Cannot iterate shipped directives: %s: %s; "
            "directive seeding skipped",
            type(exc).__name__,
            exc,
        )
        return []

    for sub in sub_iter:
        target_dir = skills_dir / sub.name
        for src_path in _walk_traversable(sub):
            rel = src_path.relative_to(sub).as_posix()
            target = target_dir / rel
            if (not force) and target.exists():
                continue
            try:
                content = src_path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError) as exc:
                import logging

                logging.getLogger(__name__).warning(
                    "Cannot read shipped directive file %s: %s; skipping",
                    src_path,
                    exc,
                )
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                target.write_text(content, encoding="utf-8")
            except OSError as exc:
                import logging

                logging.getLogger(__name__).warning(
                    "Cannot write shipped directive file %s: %s; skipping",
                    target,
                    exc,
                )
                continue
            created.append(target)
    return created


def _walk_traversable(root) -> list:
    """Walk a Traversable (``importlib.resources``) directory tree.

    Returns every file (relative paths included as ``Traversable``
    objects) under ``root``. Directories are yielded before their
    files so callers can mkdir parent paths first.
    """

    out: list = []
    try:
        children = list(root.iterdir())
    except (OSError, NotImplementedError):
        return out

    # Sort for deterministic seeding order.
    children.sort(key=lambda p: p.name)
    for child in children:
        try:
            if child.is_dir():
                out.extend(_walk_traversable(child))
            else:
                out.append(child)
        except (OSError, NotImplementedError):
            # Some Traversables cannot answer ``is_dir()``; treat as file
            out.append(child)
    return out


def _genre_scaffolding(root: Path, canonical_genre: str) -> list[Path]:
    """Create genre-specific files and return the paths that were created.

    The returned list only contains paths that were actually written;
    pre-existing files are left untouched. ``canonical_genre`` MUST be one
    of ``{历史, 言情, 玄幻, other}`` (the whitelist returned by
    :func:`_normalize_genre`); ``other`` returns ``[]``.
    """
    scaffolds: dict[str, dict[Path, str]] = {
        "历史": {
            root / "史实" / "年表.md": "# 年表\n\n按年份记录关键历史事件。\n",
            root / "史实" / "人物.md": "# 历史人物\n\n记录涉及的关键历史人物。\n",
            root / "史实" / "事件.md": "# 重大事件\n\n记录重大历史事件及其时间顺序。\n",
            root / "史实" / "考证.md": "# 考证备忘\n\n史实资料的核实状态与争议说明。\n",
        },
        "玄幻": {
            root / "伏笔" / "foreshadow.md": (
                "# 伏笔表\n\n记录伏笔编号、内容、计划回收章节。\n"
            ),
            root / "大纲" / "境界表.md": (
                "# 境界表\n\n记录修炼等级体系与各境界节点。\n"
            ),
        },
        "言情": {
            root / "人设" / "男主.md": "# 男主人设\n\n",
            root / "人设" / "女主.md": "# 女主人设\n\n",
            root / "大纲" / "感情线时间轴.md": (
                "# 感情线时间轴\n\n按关系阶段拆章。\n"
            ),
        },
    }

    mapping = scaffolds.get(canonical_genre)
    if not mapping:
        return []

    created: list[Path] = []
    for path, content in mapping.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            path.write_text(content, encoding="utf-8")
            created.append(path)
    return created


def _normalize_name(name: str) -> str:
    normalized = name.strip().replace(" ", "-")
    if not normalized:
        msg = (
            "项目名称不能为空。"
            "请传入至少一个非空白字符，例如 `writer init 我的小说`。"
        )
        raise ValueError(msg)
    return normalized


__all__ = [
    "NovelWorkspace",
    "create_new_workspace",
    "create_workspace",
]
