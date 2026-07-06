"""Novel project workspace scaffolding.

``create_workspace`` materialises the on-disk layout for a novel project.
The base layout (``manuscript / outline / characters / world / notes`` +
``AGENT.md / README.md`` + one stub per subdirectory) is **genre-agnostic**;
genre-specific extras (history ``史实/``, xuanhuan ``伏笔/``, romance
``人设/``) are layered on top by :func:`_genre_scaffolding` and merged into
the returned ``created_files`` list.

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

from writer.project.state import ProjectState, render_agent_file


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
) -> NovelWorkspace:
    project_name = _normalize_name(name)
    canonical_genre = _normalize_genre(genre)
    root = base_dir / project_name

    if root.exists() and not force:
        msg = (
            f"项目目录已存在: {root}。"
            f"如要覆盖请重新执行 `writer new {project_name} --force`，"
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
    for directory in directories:
        directory.mkdir(parents=True, exist_ok=True)

    files = {
        root / "AGENT.md": render_agent_file(
            project_name,
            ProjectState.INITIALIZED,
            genre=canonical_genre,
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

    # Genre-specific scaffolding layered on top of the base layout.
    created_files.extend(_genre_scaffolding(root, canonical_genre))

    return NovelWorkspace(root=root, created_files=created_files)


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
            "请传入至少一个非空白字符，例如 `writer new 我的小说`。"
        )
        raise ValueError(msg)
    return normalized


__all__ = [
    "NovelWorkspace",
    "create_workspace",
]
