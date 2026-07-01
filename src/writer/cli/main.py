from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from writer import __version__
from writer.agent import NovelAgent
from writer.config import get_settings
from writer.project import create_workspace

app = typer.Typer(
    name="writer",
    help="长篇小说写作 Agent CLI",
    no_args_is_help=True,
)
console = Console()


def version_callback(value: bool) -> None:
    if value:
        console.print(f"writer-agent {__version__}")
        raise typer.Exit


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option("--version", callback=version_callback, help="显示版本号"),
    ] = None,
) -> None:
    """长篇小说写作 Agent CLI。"""


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
def new_project(
    name: Annotated[str, typer.Argument(help="小说项目名称")],
    directory: Annotated[
        Path,
        typer.Option("--dir", "-d", help="项目创建到哪个目录下"),
    ] = Path("novels"),
    force: Annotated[
        bool,
        typer.Option("--force", help="允许覆盖缺失的初始化文件"),
    ] = False,
) -> None:
    """创建一个小说项目工作区。"""
    try:
        workspace = create_workspace(name, directory, force=force)
    except (FileExistsError, ValueError) as exc:
        console.print(f"[red]错误：{exc}[/red]")
        raise typer.Exit(code=1) from exc

    console.print(f"[green]已创建小说项目：[/green]{workspace.root}")
    for path in workspace.created_files:
        console.print(f"  - {path}")


@app.command()
def outline(
    idea: Annotated[str, typer.Argument(help="一句话小说创意")],
) -> None:
    """根据一句话创意生成最小大纲。"""
    settings = get_settings()
    agent = NovelAgent(settings)
    result = agent.draft_outline(idea)

    console.print(f"[bold]{result.title}[/bold]")
    console.print(result.premise)
    for chapter in result.chapters:
        console.print(f"- {chapter}")
