"""项目创建时的题材选择辅助函数。"""

from __future__ import annotations

import sys

from rich.console import Console

# 交互式多选提示中展示的规范选项。
GENRE_OPTIONS: tuple[str, ...] = ("历史", "言情", "玄幻", "科幻", "悬疑", "其他")

_GENRE_ALIASES: dict[str, str] = {
    "历史": "历史",
    "history": "历史",
    "historical": "历史",
    "言情": "言情",
    "romance": "言情",
    "玄幻": "玄幻",
    "xuanhuan": "玄幻",
    "fantasy": "玄幻",
    "科幻": "科幻",
    "sci-fi": "科幻",
    "scifi": "科幻",
    "悬疑": "悬疑",
    "mystery": "悬疑",
    "其他": "其他",
    "other": "其他",
    "其它": "其他",
}


def normalize_genre_token(raw: str) -> str:
    """把单个题材标签或别名映射为规范 key。"""

    key = (raw or "").strip().lower()
    if not key:
        return "other"
    return _GENRE_ALIASES.get(key, "other")


def normalize_genres(raw: str | list[str] | None) -> list[str]:
    """把一个或多个题材输入规范化为规范 key（去重，保持顺序）。"""

    tokens: list[str]
    if raw is None:
        tokens = []
    elif isinstance(raw, str):
        tokens = [part.strip() for part in raw.replace("，", ",").split(",") if part.strip()]
    else:
        tokens = [part.strip() for part in raw if part.strip()]

    seen: set[str] = set()
    result: list[str] = []
    for token in tokens:
        canonical = normalize_genre_token(token)
        if canonical == "other" and token and token not in _GENRE_ALIASES:
            label = token.strip()
            if label not in seen:
                seen.add(label)
                result.append(label)
            continue
        if canonical not in seen:
            seen.add(canonical)
            result.append(canonical)
    return result


def primary_genre(genres: list[str]) -> str:
    """为 agent 选择挑出第一个已知题材。"""

    for genre in genres:
        if genre in {"历史", "言情", "玄幻"}:
            return genre
    return "other"


def format_genre_line(genres: list[str]) -> str | None:
    """渲染 ``AGENT.md`` 的 ``题材:`` 行。"""

    labels = [
        genre
        for genre in genres
        if genre and genre not in {"other", "其他", "其它"}
    ]
    if not labels:
        return None
    return ", ".join(labels)


def prompt_genres(
    console: Console | None = None,
    *,
    default: list[str] | None = None,
) -> list[str]:
    """交互式让用户选择一种或多种题材。

    非 TTY stdin 回退到 ``default`` 或 ``["其他"]``。
    """

    out = console or Console()
    if default is not None:
        return normalize_genres(default)

    if not sys.stdin.isatty():
        return normalize_genres(["其他"])

    out.print("请选择小说题材（可多选，输入编号，逗号分隔，例如 1,3）：")
    for index, label in enumerate(GENRE_OPTIONS, start=1):
        out.print(f"  {index}. {label}")

    while True:
        raw = input("题材编号: ").strip()
        if not raw:
            out.print("[yellow]请至少选择一种题材。[/yellow]")
            continue
        try:
            indices = [int(part.strip()) for part in raw.replace("，", ",").split(",") if part.strip()]
        except ValueError:
            out.print("[yellow]请输入有效编号，例如 1,3[/yellow]")
            continue
        if not indices:
            out.print("[yellow]请至少选择一种题材。[/yellow]")
            continue
        if any(index < 1 or index > len(GENRE_OPTIONS) for index in indices):
            out.print(f"[yellow]编号需在 1–{len(GENRE_OPTIONS)} 之间。[/yellow]")
            continue
        picked = [GENRE_OPTIONS[index - 1] for index in indices]
        return normalize_genres(picked)


__all__ = [
    "GENRE_OPTIONS",
    "format_genre_line",
    "normalize_genre_token",
    "normalize_genres",
    "primary_genre",
    "prompt_genres",
]
