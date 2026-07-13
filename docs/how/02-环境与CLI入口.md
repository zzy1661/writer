# 02 · 环境与 CLI 入口

> 对应代码:`pyproject.toml` + `src/writer/__main__.py` + `src/writer/cli/main.py` + `writer.spec`
> 设计备忘:[`备忘 08-REPL交互体验`](../../技术难点与解决方案备忘/08-REPL交互体验与命令解析.md)

---

## 2.1 环境约束

- **Python ≥ 3.12**(`pyproject.toml` 的 `requires-python`)
- **包管理**:[uv](https://docs.astral.sh/uv/),自带 Python 管理,不需要手动安装 Python
- **LLM(可选)**:OpenAI 兼容协议,可走 deepseek-v3 / GPT 等;未配置 API key 时自动降级到「rule-only」模式

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
│       ├── cli/main.py        # Typer + Rich + prompt_toolkit
│       ├── session/           # 跨 turn 状态
│       ├── engine/            # AsyncGenerator 状态机
│       ├── routing/           # IntentRouter Protocol
│       ├── tools/             # Tool 协议 + 9 builtin
│       ├── skills/            # SKILL.md directives
│       ├── agents/            # AgentRegistry + 4 份题材 .md
│       ├── workflows/         # 写章节 / 审核 stub
│       ├── llm/               # ReActAgent + Provider
│       ├── project/           # workspace 脚手架
│       ├── config/            # pydantic-settings
│       ├── prompts/           # LLM prompt 模板(字符串字面量)
│       └── agent/             # 兼容层 re-export
├── tests/                     # pytest + pytest-asyncio
├── e2e/                       # e2e 测试项目(REPL stdin)
├── docs/                      # 设计文档 + how 教程
├── 技术难点与解决方案备忘/     # 17 个技术决策备忘
├── openspec/                  # OpenSpec 提案(变更管理)
└── scripts/                   # 杂项脚本
```

## 2.3 安装

```bash
# 同步依赖(自动建 .venv + 装包 + 所有 extras)
uv sync --all-extras

# 复制环境变量模板
cp .env.example .env

# 编辑 .env 填入 WRITER_API_KEY
```

## 2.4 CLI 入口

`pyproject.toml` 注册的脚本:

```toml
[project.scripts]
writer = "writer.cli.main:app"
```

也就是说 `uv run writer` 实际调用 `writer/cli/main.py::app`(一个 Typer 应用)。

## 2.5 Typer 子命令一览

`src/writer/cli/main.py` 用 Typer 注册了 4 个子命令:

| 子命令 | 作用 | 调用路径 |
| ------ | ---- | -------- |
| `writer` | 默认进入 REPL | `_run_repl()` |
| `writer doctor` | 检查模型、API Key、Base URL 配置 | `doctor()` Typer callback |
| `writer new <书名>` | 创建新书项目(含 `.writer/`、`创意/`、多题材提示) | `new()` Typer callback |
| `writer outline <创意>` | 同 REPL `/大纲` 命令(走同一条路径) | `outline()` Typer callback |

### 伪代码:app 启动

```python
import typer
app = typer.Typer(name="writer", help="长篇小说写作 Agent CLI", no_args_is_help=False)

@app.callback(invoke_without_command=True)
def main(ctx: typer.Context, version: bool = False):
    """默认入口: 进入 REPL。"""
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
    if not genre:
        genre = [prompt_genre()]  # 交互式 prompt:历史/言情/玄幻/其他
    workspace = create_new_workspace(name, Path(dir), genre=genre, force=force)
    console.print(f"已创建: {workspace.root}")

@app.command()
def outline(brief: str):
    """生成大纲(等同 REPL /大纲)。"""
    _run_one_shot_engine(brief)
```

## 2.6 REPL 主循环

`src/writer/cli/main.py::_run_repl()` 启动一个 `PromptSession`,循环读取用户输入,每行调用 `handle_repl_input(line, session)`。

### 核心代码

```python
def _run_repl() -> None:
    settings = load_project_settings()
    project_root = discover_project_root()
    session = EngineSession(project_root=project_root, deps=production_deps(...))
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

### 伪代码:handle_repl_input

```python
def handle_repl_input(line: str, session: EngineSession) -> bool:
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
    if text.startswith("/init ") and "--" in text:
        # flag 形式(走 Typer 风格交互 prompt)
        handle_init_with_flags(text, session); return True

    # 2. 拼 pending interrupt(若有)
    final_input = compose_pending_input(text, session.pending_interrupt)

    # 3. 构造 ctx + 跑引擎
    ctx = EngineContext(
        user_input=final_input,
        project_root=session.project_root,
        project_state=session.project_state,
        session_id=str(session.session_id),
    )
    config = build_engine_config(ctx)
    asyncio.run(_run_engine(ctx, session.deps, config, session))
    return True
```

### 关键设计

- **`PromptSession`**:prompt_toolkit 提供,内置历史(↑/↓)、Tab 补全、`Ctrl+R` 反向搜索
- **历史文件**:`~/.config/writer/history`,跨 session 持久
- **`WordCompleter`**:Tab 补全命令名,从 `DirectiveRegistry.help_entries()` 派生
- **`SLASH_CMD_PATTERN`**:正则 `[/\w\u4e00-\u9fff]+`,保证 `/大纲` 不会被切成 `//大纲`(中文也支持)

## 2.7 `_run_engine`:CLI ↔ Engine 桥接

CLI 在 `_run_engine` 里逐事件消费引擎的 AsyncGenerator,并按事件类型渲染:

```python
async def _run_engine(ctx, deps, config, session):
    pending = None
    async for event in run_engine(ctx, deps, config=config):
        match event:
            case TextChunk(text=t):
                console.print(t, markup=False, highlight=False)  # 防 Rich 吞 [xxx]
            case ActionEvent(action=a):
                # 不渲染(用户只需要看结果)
                pass
            case ToolCall(name=n, arguments=args):
                console.print(f"[tool] {n}({args})")
            case ToolResult(name=n, output=o):
                console.print(f"[result] {o[:200]}...")
            case Interrupt(type=ty, prompt=p, options=opts):
                pending = (ty, p, opts)
            case Done(reason=r, payload=payload):
                console.print(f"[done] {r}")
                session.record_turn(text, r)
                session.clear_pending_interrupt()
                # 若是 /init 创建项目,绑定 project_root
                if r == "answered" and payload.get("project_root"):
                    session.set_project_root(Path(payload["project_root"]))
            case ErrorEvent(message=m, traceback=tb):
                console.print(f"[red]{m}[/red]")
                if tb:
                    console.print(f"[dim]{tb}[/dim]")
```

### 关键陷阱

- **`markup=False, highlight=False`** —— Rich 默认会把 `[xxx]` 当 markup,会把文本里的方括号吞掉。LLM 输出的 Markdown 链接 / 列表 / 强调都包含方括号,必须关掉 markup。
- **session 与 engine 解耦** —— engine 不知道 session 存在,所有跨 turn 状态在 CLI 层维护。
- **`project_root` 反向回填** —— 当 `/init` 走 `command_pending`/`answered` 路径创建项目时,payload 里会有 `project_root`,CLI 负责调用 `session.set_project_root(path)` 把新项目绑回去。

## 2.8 e2e 管道

`e2e/` 目录下有一个最小项目,可直接用 stdin 喂 REPL:

```bash
printf "/大纲 一个穿越到唐朝的程序员\n" | .venv/bin/writer
```

这套 e2e 用于快速验证五种 Done 分支(answered / workflow_pending / tool_pending / command_pending / ask_user / tool_loop_completed)。

## 2.9 测试入口

```bash
uv run pytest                                       # 全量(基线 ~339 个测试)
uv run pytest tests/test_engine.py                  # 单文件
uv run pytest -k router                             # 按名字匹配
uv run pytest tests/test_engine.py::test_router_... # 单测
uv run pytest -x --tb=short                         # 失败即停 + 紧凑回溯
uv run pytest --cov=writer                          # 覆盖率
```

---

## 2.10 进一步阅读

- [03-会话与状态机](03-会话与状态机.md) —— `EngineSession` 细节
- [05-引擎核心](05-引擎核心.md) —— `run_engine` 与 Done 分支
- [13-打包与发布](13-打包与发布.md) —— PyInstaller