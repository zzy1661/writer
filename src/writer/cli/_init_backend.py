"""init 共享后端：``init_project`` / ``_maybe_apply_init_brief``。

把 ``writer new``（Typer ``new`` 子命令）与 REPL ``/init --flag``
共用的项目初始化逻辑独立成模块，让 ``commands`` 与 ``repl`` 都
依赖这个统一入口而不直接依赖彼此。``writer.cli.repl.console``
作为共享的 Rich Console 单例被复用。
"""

from __future__ import annotations

import sys
from pathlib import Path

import typer

from writer.cli.repl import console
from writer.config import get_settings, load_project_settings, refresh_settings
from writer.project import create_workspace, normalize_genres
from writer.project.init_brief import apply_init_brief


def _normalize_cli_genre(raw: str) -> str:
    """把 CLI 侧的题材字符串映射为规范 key（遗留的单一题材辅助）。"""

    from writer.project.genre import normalize_genre_token

    return normalize_genre_token(raw)


def init_project(
    name: str,
    directory: Path,
    *,
    force: bool = False,
    genre: str | None = None,
    genres: list[str] | None = None,
    brief: str | None = None,
    skip_brief: bool = False,
) -> str:
    """Typer ``init`` 子命令与 REPL ``/init`` 共用的后端。

    返回使用的规范题材标签（用于 session 绑定）。
    """
    genre_list = normalize_genres(genres if genres is not None else ([genre] if genre else ["other"]))
    from writer.project.genre import format_genre_line, primary_genre

    resolved_genre = format_genre_line(genre_list) or primary_genre(genre_list)
    try:
        workspace = create_workspace(
            name,
            directory,
            force=force,
            genres=genre_list,
            with_ideas_dir=True,
        )
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]已创建小说项目：[/green]{workspace.root}")
    console.print(f"题材：{resolved_genre}")
    for path in workspace.created_files:
        console.print(f"  - {path}")

    _maybe_apply_init_brief(
        workspace.root, brief=brief, skip_brief=skip_brief, genre=resolved_genre
    )

    console.print(
        "[dim]提示：在同一目录执行 `uv run writer` 进入 REPL 时会自动绑定此项目。[/dim]"
    )
    return resolved_genre


def _maybe_apply_init_brief(
    project_root: Path,
    *,
    brief: str | None,
    skip_brief: bool,
    genre: str,
) -> None:
    if skip_brief:
        return

    user_brief = brief
    if user_brief is None and sys.stdin.isatty():
        console.print(
            "\n[cyan]请用自然语言描述你的小说创意与基本要求[/cyan]"
            "（直接回车跳过）："
        )
        user_brief = typer.prompt("", default="", show_default=False)

    if not user_brief or not user_brief.strip():
        return

    load_project_settings(project_root)
    refresh_settings()
    # ``process_init_brief``（``chg-remove-roles`` 后唯一幸存的
    # Python-side 能力）通过 :func:`writer.project.init_brief.apply_init_brief`
    # 调用；不需要 ``deps.story_agent``。
    result = apply_init_brief(project_root, user_brief.strip(), settings=get_settings())
    console.print(f"[green]已写入 创意/核心创意.md[/green]（来源: {result.source}）")
    console.print("[green]已更新 AGENT.md 基本要求[/green]")
