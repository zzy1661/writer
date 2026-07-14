# REPL 交互体验与命令解析

## 业务背景

Writer Agent 不是简单脚本,而是用户长期使用的写作 REPL。用户会频繁输入中文命令、多行创意、章节定位、修订指令,也需要历史、补全、中断和分页阅读。

## 技术难点

中文命令和自然语言参数混杂,例如 `/创作 1.3`、`/创作 卷一第三章`、`/创作 第一章·夜奔` 都要解析到同一章节。多行输入既要适合粘贴长创意,又不能误吞普通命令。长输出需要可读渲染,中断时还要保存或丢弃半成品。

## 解决方案

CLI 层拆成三部分:

- 命令解析器:识别主命令、别名、子动词、参数。
- 对象定位器:解析章节 ID、标题、人物名、伏笔 ID。
- REPL 外壳:负责 prompt-toolkit 历史、补全、多行输入和 Rich 输出。

多行输入统一使用行首 `"""` 起止。章节定位按优先级解析:数字 ID → 中文卷章 → 标题匹配。歧义时不猜测,列出候选并要求用户用更精确形式。

## 最小 demo / 伪代码

```python
from dataclasses import dataclass


@dataclass
class ParsedCommand:
    name: str
    args: list[str]
    raw: str


def parse_command(line: str) -> ParsedCommand:
    parts = line.strip().split()
    if not parts or not parts[0].startswith("/"):
        return ParsedCommand(name="/自然语言", args=[line], raw=line)
    return ParsedCommand(name=parts[0], args=parts[1:], raw=line)


def locate_chapter(raw: str | None, toc: dict[str, str]) -> str:
    if raw is None:
        return next_unwritten_chapter(toc)
    if raw in toc:
        return raw

    candidates = [chapter_id for chapter_id, title in toc.items() if raw in title]
    if len(candidates) == 1:
        return candidates[0]
    if len(candidates) > 1:
        raise ValueError(f"章节标题有歧义,候选: {candidates}")

    return parse_chinese_chapter_id(raw)
```

## 核心依赖版最小代码

```python
from prompt_toolkit import PromptSession
from prompt_toolkit.completion import WordCompleter
from prompt_toolkit.history import FileHistory
from rich.console import Console


# 静态框架命令 + shipped SKILL.md directive 命令(2026-07-09 实测)
# `STATIC_REPL_COMMANDS` 是硬编码列表;
# `built_directive_registry().help_entries()` 拉取项目级覆盖后的实际命令;
# `build_repl_commands(directive_registry)` 把两者拼起来
STATIC_REPL_COMMANDS = [
    ("/init", "创建项目"),
    ("/状态", "查看 session 与项目状态"),
    ("/帮助", "列出可用命令"),
    ("/退出", "退出 REPL"),
]
SHIPPED_DIRECTIVE_COMMANDS = [
    "/大纲", "/目录",
]


def build_completer(directive_registry) -> WordCompleter:
    commands = (
        [cmd for cmd, _ in STATIC_REPL_COMMANDS]
        + SHIPPED_DIRECTIVE_COMMANDS
        + [cmd for cmd, _ in directive_registry.help_entries()]
        + ["/创作", "/审核", "/字数统计", "/exit", "/quit"]
    )
    return WordCompleter(sorted(set(commands)), ignore_case=True)


def run_repl(directive_registry) -> None:
    console = Console()
    session = PromptSession(
        history=FileHistory("~/.config/writer/history"),
        completer=build_completer(directive_registry),
    )

    while True:
        line = session.prompt("writer> ")
        command = parse_command(line)
        if command.name in {"/退出", "/exit", "/quit", "/q"}:
            break
        console.print(f"[blue]解析命令:[/blue] {command.name} {command.args}")
```

**关键差异**:实际 `cli/main.py::build_repl_commands(directive_registry)` 不硬编码命令名,而是从 `DirectiveRegistry.help_entries()` + `STATIC_REPL_COMMANDS` 派生。新增 shipped directive 或项目级覆盖的 directive 自动出现在 `/帮助` 和 Tab 补全里,**不需要改 CLI 代码**。

## 落地建议

- 不把 Typer 命令和 REPL 命令完全绑死:Typer 负责入口,REPL 内部使用自有命令注册表。
- 建立 `ChapterLocator`,从 `目录/目录.md` 解析章节索引。
- 帮助系统由命令注册表生成,避免文档和实现分离。
- Ctrl+C 时通知会话控制层 flush checkpoint,并询问半成品处理策略。

## 验收标准

- `/创作 1.3`、`/创作 卷一第三章`、`/创作 第一章标题` 都能正确定位章节。
- 标题重复时必须提示候选,不能随机选一个。
- (历史) 多行 `/init """..."""` 是 v2 候选特性;截至 2026-07-14 `writer-agent` 走 prompt_toolkit 单行读取,长文本用户直接粘贴即可。
- `/审核` 长报告可以分页阅读,章节正文可以用 Markdown 样式渲染。
