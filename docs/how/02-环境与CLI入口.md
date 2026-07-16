# 02 · 环境与 CLI 入口

> 对应代码：`pyproject.toml` + `src/writer/__main__.py` + `src/writer/cli/{main,commands,repl,_init_backend}.py` + `writer.spec`
> 设计备忘：[`备忘 08-REPL交互体验`](../../技术难点与解决方案备忘/08-REPL交互体验与命令解析.md)
>
> **2026-07-14 修订**：本文原版本把 CLI 入口全部写在 `cli/main.py`、列出 `writer outline` 子命令、引用测试基线 ~339。
> 截至 2026-07-14，CLI 已拆分为 `main.py` + `commands.py` + `repl.py` + `_init_backend.py` 四个文件；只剩 `writer doctor` / `writer new <书名>` 两个 Typer 子命令（`writer outline` 等价命令已下线）；测试基线 **483**。

---

## 2.1 环境约束

- **Python ≥ 3.12**（`pyproject.toml` 的 `requires-python`）
- **包管理**：[uv](https://docs.astral.sh/uv/)，自带 Python 管理，不需要手动安装 Python
- **LLM（可选）**：OpenAI 兼容协议，可走 deepseek-v3 / GPT 等；未配置 API key 时自动降级到「rule-only」模式（`tool_loop=None`，engine 走同步 `_run_tool`）

## 2.2 项目结构

```
writer-agent/
├── pyproject.toml            # 项目元数据 + 依赖
├── uv.lock                    # 锁定版本
├── writer.spec                # PyInstaller 打包配置
├── .env.example               # 环境变量模板
├── src/
│   └── writer/                # 主包
│       ├── __init__.py
│       ├── __main__.py        # `python -m writer` 入口
│       ├── cli/
│       │   ├── main.py        # Typer app + REPL 启动 + 渲染 helper
│       │   ├── commands.py    # doctor / new 子命令实现
│       │   ├── repl.py        # handle_repl_input + PromptSession + _run_runner 桥接
│       │   └── _init_backend.py  # REPL 抢先消费的 /init <brief> 后端
│       ├── session/           # Engine 跨 turn 状态
│       ├── engine/            # Engine 主类 + AsyncGenerator 状态机
│       │                     # (engine.py + loop.py compat shim + events/context/deps/config)
│       ├── routing/           # IntentRouter Protocol + 3 实现
│       ├── tools/             # Tool 协议 + 9 builtin
│       ├── skills/            # SKILL.md directives (2 shipped: /大纲 /目录)
│       ├── agents/            # AgentRegistry + 4 份题材 .md + process_init_brief capability
│       ├── workflows/         # LangGraph write_chapter (PR2) + review_chapter (PR3)
│       ├── llm/               # ReActAgent + Provider + prose clients
│       ├── project/           # workspace 脚手架 + chapter_summaries + init_brief
│       ├── config/            # pydantic-settings
│       ├── prompts/           # LLM prompt 模板（含 context.py）
│       └── agent/             # 兼容层 re-export
├── tests/                     # pytest + pytest-asyncio（基线 483）
├── e2e/                       # e2e 测试项目（REPL stdin）
├── docs/                      # 设计文档 + how 教程
├── 技术难点与解决方案备忘/     # 17 个技术决策备忘
├── openspec/                  # OpenSpec 提案（变更管理）
└── scripts/                   # 杂项脚本
```

## 2.3 安装

```bash
# 同步依赖（自动建 .venv + 装包 + 所有 extras）
uv sync --all-extras

# 复制环境变量模板
cp .env.example .env

# 编辑 .env 填入 WRITER_API_KEY
```

## 2.4 CLI 入口

`pyproject.toml` 注册的脚本：

```toml
[project.scripts]
writer = "writer.cli.main:app"
```

也就是说 `uv run writer` 实际调用 `writer/cli/main.py::app`（一个 Typer 应用）。

## 2.5 Typer 子命令一览

> **2026-07-14 修订**：原 `writer outline` 子命令已下线；当前只剩 `doctor` / `new` 两个 Typer 子命令（`writer` 默认进入 REPL）。

`src/writer/cli/commands.py` 实现：

| 子命令              | 作用                                                  | 调用路径                          |
| ------------------- | ----------------------------------------------------- | --------------------------------- |
| `writer`            | 默认进入 REPL                                          | `cli/main.py::_run_repl`          |
| `writer doctor`     | 检查模型、API Key、Base URL 配置                       | `commands.py::doctor`             |
| `writer new <书名>` | 创建新书项目（含 `.writer/`、`创意/`、多题材提示）     | `commands.py::new`                |

> 其他命令（`/大纲`、`/目录`、`/创作`、`/审核`、`/init <brief>` 等）只在 REPL 内部使用；没有 Typer 子命令镜像。

### 伪代码：app 启动

```python
import typer
app = typer.Typer(name="writer", help="长篇小说写作 Agent CLI", no_args_is_help=False)

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = False):
    """默认入口：进入 REPL。"""
    if version:
        print_version(); raise typer.Exit
    if ctx.invoked_subcommand is None:
        _run_repl()  # 默认启动 REPL

@app.command()
def doctor():
    """检查配置。"""
    settings = get_settings()
    console.print(f"Model:    {settings.model}")
    console.print(f"Base URL: {settings.base_url}")
    console.print(f"API Key:  {'已配置' if settings.has_api_key else '未配置'}")

@app.command()
def new(name: str, genre: list[str] = typer.Option([], "-g", "--genre"), dir: str = ".", force: bool = False):
    """创建新书项目。"""
    workspace = create_new_workspace(name, Path(dir), genres=genre or None, force=force)
    console.print(f"已创建: {workspace.root}")
```

## 2.6 REPL 主循环

`src/writer/cli/repl.py::_run_repl()` 启动一个 `PromptSession`，循环读取用户输入，每行调用 `handle_repl_input(line, session)`。

### 核心代码

```python
def _run_repl() -> None:
    settings = load_project_settings()
    project_root = discover_project_root()
    session = Engine(project_root=project_root)  # __post_init__ 装配 RunnerDeps 后包装 Engine
    print_welcome()

    history = FileHistory(str(HISTORY_FILE))
    completer = WordCompleter(build_repl_commands(...), pattern=SLASH_CMD_PATTERN)
    prompt_session: PromptSession[str] = PromptSession(history=history, completer=completer)

    while True:
        try:
            line = prompt_session.prompt(REPL_PROMPT)
        except KeyboardInterrupt:
            continue
        except EOFError:
            break
        if not handle_repl_input(line, session):
            break
```

### 伪代码：handle_repl_input

> **2026-07-14 修订**：REPL `/init --name X --dir Y` flag 形式已删除。REPL `/init` 后只跟故事核心创意；创建项目请用 CLI 子命令 `writer new <书名>`。`_try_handle_repl_init_brief` 在 engine 派发**之前**拦截,调 `prompt_genres` + `apply_genre_and_brief` 一站式完成「补脚手架 + 写 brief」。
>
> **2026-07-13 历史**:`_try_handle_repl_init_brief` 抢先消费特性早在 2026-07-13 落地;在那之前 REPL `/init <name>` 走 flag 形式 + `_parse_repl_init_argv`,与 Typer 子命令行为对齐。2026-07-14 收紧后只剩 brief 形式。

```python
def handle_repl_input(line: str, session: Engine) -> bool:
    text = line.strip()
    if not text:
        return True

    # 1. 框架命令:不交给 engine
    if text in EXIT_COMMANDS:
        console.print("[green]已退出 writer。[/green]")
        return False
    if text in HELP_COMMANDS:
        print_repl_help()
        return True
    if text == "/状态":
        show_status(session); return True

    # 2. REPL 抢先消费:/init <创意> 多选题材 + 写 brief
    if text.startswith("/init ") and _try_handle_repl_init_brief(text, session):
        return True

    # 3. 委派给 session.run_turn()(构造 ctx 并调 engine.run)
    asyncio.run(_run_runner(text, session, console))
    return True
```

### 关键设计

- **`PromptSession`**：prompt_toolkit 提供，内置历史（↑/↓）、Tab 补全、`Ctrl+R` 反向搜索
- **历史文件**：`~/.config/writer/history`，跨 session 持久
- **`WordCompleter`**：Tab 补全命令名，从 `DirectiveRegistry.help_entries()` 派生
- **`SLASH_CMD_PATTERN`**：正则 `[/\w\u4e00-\u9fff]+`，保证 `/大纲` 不会被切成 `//大纲`（中文也支持）
- **REPL 路由原则**：除框架命令（`/退出`、`/帮助`、`/状态`）外全交给 engine，避免 CLI 层重复维护命令路由

## 2.7 `_run_runner`：CLI ↔ Engine 桥接

CLI 在 `cli/repl.py::_run_runner` 里通过 `session.run_turn(user_input)` 拿到 AsyncGenerator，并逐事件消费：

```python
async def _run_runner(user_input: str, session: Engine, console: Console) -> None:
    session.refresh_project_state()
    async for event in session.run_turn(user_input):
        match event:
            case TextChunk(text=t):
                console.print(t, markup=False, highlight=False)  # 防 Rich 吞 [xxx]
            case ActionEvent(action=a):
                console.print(f"[dim]→ {a.action_type}[/dim]")
            case ToolCall(name=n):
                console.print(f"[tool] {n}")
            case ToolResult(name=n, output=o):
                console.print(f"[result] {o[:200]}...")
            case Interrupt() as interrupt:
                pending = interrupt
                session.set_pending_interrupt(interrupt)
            case Done(reason=r, payload=payload):
                console.print(f"[done] {r}")
                session.record_turn(user_input, r)
                session.clear_pending_interrupt()
            case ErrorEvent(message=m, traceback=tb):
                console.print(f"[red]{m}[/red]")
                if tb:
                    console.print(f"[dim]{tb}[/dim]")
```

### 关键陷阱

- **`markup=False, highlight=False`** —— Rich 默认会把 `[xxx]` 当 markup，会把文本里的方括号吞掉。LLM 输出的 Markdown 链接 / 列表 / 强调都包含方括号，必须关掉 markup。
- **session / engine / Engine 三层解耦** —— `session` 持跨 turn 状态；`session.engine: Engine` 持 `RunnerDeps` + `RunnerConfig`；`engine.run(ctx)` 是纯函数式事件流。CLI 不需要 import `RunnerDeps`。
- ~~**`project_root` 反向回填** —— 当 `/init` 走 `answered` 路径创建项目时,payload 里会有 `project_root`,CLI 负责调用 `session.set_project_root(path)` 把新项目绑回去~~(per 2026-07-14 收紧:REPL `/init` 不再创建项目,该流程删除;创建项目的 payload 反向回填逻辑仍保留 `Engine._run_init_command`,作为 SDK / e2e pipe 等非 REPL 调用方创建项目的兜底通道)。

## 2.8 e2e 管道

`e2e/` 目录下有一个最小项目，可直接用 stdin 喂 REPL：

```bash
printf "/大纲 一个穿越到唐朝的程序员\n" | .venv/bin/writer
```

这套 e2e 用于快速验证七种 Done 分支：

- `answered` —— `/大纲` 命中 directive / 自然语言命中 LLM 回答
- `workflow_completed` —— `/创作` 走 LangGraph `write_chapter` 跑完
- `tool_completed` —— rule-only 部署走同步 `_run_tool`
- `tool_loop_completed` —— LLM 工具循环 `MAX_LOOP_STEPS=5` 优雅耗尽
- `command_pending` —— 未实装的斜杠命令占位
- `ask_user` —— router 主动反问
- `aborted` —— `except ToolError` / `except SkillError` / `except Exception` 三层兜底

## 2.9 测试入口

```bash
uv run pytest                                       # 全量（基线 483 个测试，per 2026-07-14 实测）
uv run pytest tests/test_engine.py                  # 单文件
uv run pytest -k router                             # 按名字匹配
uv run pytest tests/test_engine.py::test_router_... # 单测
uv run pytest -x --tb=short                         # 失败即停 + 紧凑回溯
uv run pytest --cov=writer                          # 覆盖率
```

---

## 2.10 进一步阅读

- [03-会话与状态机](03-会话与状态机.md) —— `Engine` 细节
- [05-引擎核心](05-引擎核心.md) —— `Engine.run` 与 Done 分支
- [13-打包与发布](13-打包与发布.md) —— PyInstaller