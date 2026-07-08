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

    created.extend(_seed_skill_mirrors(writer_root, force=force))
    return created


def _seed_skill_mirrors(
    writer_root: Path, *, force: bool = False
) -> list[Path]:
    """Mirror each built-in skill's Python source into
    ``<writer_root>/skills/<mirror_filename>.py`` plus a companion
    ``.md`` doc file.

    Called by :func:`_writer_meta_scaffolding` when ``with_writer_meta=True``.
    Per-skill failures (e.g. source module missing) are logged at WARNING
    and skipped — a single broken skill MUST NOT prevent other skills
    from being mirrored and MUST NOT prevent the workspace from being
    created.

    Files that already exist on disk are left untouched unless
    ``force=True`` (matches the same convention as
    :func:`create_workspace`).
    """

    skills_dir = writer_root / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    # Local import: importing writer.skills.builtin_sources at module
    # load time would pull in the full writer.skills package, which
    # imports the built-in skill classes; those classes import
    # writer.roles which imports writer.project → circular. The
    # builtin_sources module itself is a leaf with no further
    # dependencies, so a function-local import is safe.
    from writer.skills.builtin_sources import BUILTIN_SKILL_SOURCES  # noqa: PLC0415

    created: list[Path] = []
    for src in BUILTIN_SKILL_SOURCES:
        for filename, content in _render_skill_mirror(src):
            target = skills_dir / filename
            if (not force) and target.exists():
                continue
            try:
                target.write_text(content, encoding="utf-8")
            except OSError as exc:
                # Project may be on a read-only mount; warn and keep going
                # so the rest of the workspace can still be created.
                import logging

                logging.getLogger(__name__).warning(
                    "Failed to write project skill mirror %s: %s; skipping",
                    target,
                    exc,
                )
                continue
            created.append(target)
    return created


def _render_skill_mirror(src: object) -> list[tuple[str, str]]:
    """Return ``[(filename, content), ...]`` for one built-in skill source.

    Produces two files: ``<mirror_filename>.py`` (1:1 copy of the
    source module's text + a header explaining the project-level
    override semantics) and ``<mirror_filename>.md`` (user-facing
    doc with the title and body from the registry).
    """

    from writer.skills.builtin_sources import (  # noqa: PLC0415
        MIRROR_HEADER_TEMPLATE,
        BuiltinSkillSource,
    )


    assert isinstance(src, BuiltinSkillSource)

    source_path = _resolve_source_path(src)
    source_text = (
        source_path.read_text(encoding="utf-8")
        if source_path is not None
        else (
            f'# Source module "{src.source_module}" not importable; the\n'
            "# project-level skill below cannot mirror its real implementation.\n"
            f"# Class: {src.class_name}\n\n"
            "raise NotImplementedError(\n"
            f'    "Source module {src.source_module!r} is not importable; "\n'
            '    "please file a bug at the writer-agent issue tracker."\n'
            ")\n"
        )
    )

    header = MIRROR_HEADER_TEMPLATE.format(
        command=src.command,
        source_module_last=src.source_module.rsplit(".", 1)[-1],
        class_name=src.class_name,
        source_sha256=src.source_sha256,
    )

    py_content = header + source_text
    md_content = f"# {src.doc_title}\n\n{src.doc_body}\n"

    return [
        (f"{src.mirror_filename}.py", py_content),
        (f"{src.mirror_filename}.md", md_content),
    ]


def _resolve_source_path(src: object) -> Path | None:
    """Locate the on-disk path of ``src.source_module`` for reading.

    Walks ``sys.modules`` to find the module object and then reads
    its ``__file__`` attribute. Returns ``None`` when the module is
    not importable in the current Python process (so the caller can
    fall back to a placeholder body).
    """

    import importlib
    import sys

    from writer.skills.builtin_sources import BuiltinSkillSource  # noqa: PLC0415

    assert isinstance(src, BuiltinSkillSource)
    module = sys.modules.get(src.source_module)
    if module is None:
        try:
            module = importlib.import_module(src.source_module)
        except Exception:
            return None
    file_attr = getattr(module, "__file__", None)
    if not file_attr:
        return None
    return Path(file_attr)


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
