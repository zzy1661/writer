"""Genre selection helpers for project creation."""

from __future__ import annotations

import sys

from rich.console import Console

# Canonical options shown in the interactive multi-select prompt.
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
    """Map a single genre label or alias to a canonical key."""

    key = (raw or "").strip().lower()
    if not key:
        return "other"
    return _GENRE_ALIASES.get(key, "other")


def normalize_genres(raw: str | list[str] | None) -> list[str]:
    """Normalize one or many genre inputs into canonical keys (deduped, order kept)."""

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
    """Pick the first known genre for consultant selection."""

    for genre in genres:
        if genre in {"历史", "言情", "玄幻"}:
            return genre
    return "other"


def format_genre_line(genres: list[str]) -> str | None:
    """Render the ``题材:`` line for ``AGENT.md``."""

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
    """Interactively ask the user to pick one or more genres.

    Non-TTY stdin falls back to ``default`` or ``["其他"]``.
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
