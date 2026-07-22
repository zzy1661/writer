"""Typer 子命令层：``app`` 实例 + ``doctor`` / ``new`` 子命令 + ``main`` 回调。

无子命令调用时（``writer`` 不带参数）默认进入 REPL（``repl.run_repl``）。
``new`` 子命令直接通过 :func:`writer.project.create_new_workspace`
创建项目；REPL 不再暴露 ``/init --name X --dir Y`` flag 形式
（per 2026-07-14 收紧），创建项目的唯一入口是本子命令。
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import typer
from rich.panel import Panel
from rich.table import Table

from writer import __version__
from writer.cli.repl import console, run_repl
from writer.config import get_settings
from writer.project import create_new_workspace

app = typer.Typer(
    name="writer",
    help="长篇小说写作 Agent CLI",
    no_args_is_help=False,
)


def version_callback(value: bool) -> None:
    if value:
        console.print(f"writer-agent {__version__}")
        raise typer.Exit


@app.callback(invoke_without_command=True)
def main(
    ctx: typer.Context,
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, help="显示版本号"),
    ] = None,
) -> None:
    """长篇小说写作 Agent CLI。"""
    if ctx.invoked_subcommand is None:
        run_repl()


@app.command()
def doctor() -> None:
    """检查当前配置是否可用。"""
    settings = get_settings()

    table = Table(title="writer-agent doctor")
    table.add_column("项目")
    table.add_column("状态")
    table.add_row("模型", settings.model)
    table.add_row("Base URL", settings.base_url)
    table.add_row("API Key", "已配置" if settings.has_api_key else "未配置")
    table.add_row("Temperature", str(settings.temperature))

    console.print(table)


@app.command("new")
def new_project_cmd(
    name: Annotated[str, typer.Argument(help="小说书名（目录名）")],
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="项目创建到哪个目录下"),
    ] = Path("."),
    force: Annotated[
        bool,
        typer.Option("--force", help="允许覆盖缺失的初始化文件"),
    ] = False,
) -> None:
    """创建带 ``.writer/`` 元数据与 ``创意/`` 目录的新书项目。"""
    try:
        workspace = create_new_workspace(
            name,
            directory,
            force=force,
        )
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]已创建新书项目：[/green]{workspace.root}")
    for path in workspace.created_files:
        console.print(f"  - {path}")
    console.print(
        "[dim]项目 LLM 配置位于 .writer/config（优先级高于 .env）。[/dim]"
    )

    # per 2026-07-23: 引导用户编辑 ``创意/简介.md`` 并运行 ``/start``。
    # ``/start`` 是 REPL 启动 explore 多轮创作的入口(取代旧的
    # ``/init <brief>`` 形式)。
    console.print(
        Panel(
            f"[bold cyan]{workspace.root.name}[/bold cyan] 已创建\n\n"
            "下一步：\n"
            "  1. 编辑 [bold]创意/简介.md[/bold] 写上核心创意\n"
            "  2. 在 REPL 中运行 [bold]/start[/bold] 开始创作",
            title="[green]✓[/green]",
            border_style="green",
        )
    )


__all__ = [
    "app",
    "doctor",
    "main",
    "new_project_cmd",
    "version_callback",
]
