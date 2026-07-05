# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目定位

`writer-agent` 是一个**长篇小说写作 CLI**（中文），目标是辅助用户完成 20-50 万字小说的构思、规划、分章、正文生成与修订。

## 常用命令

环境：[uv](https://docs.astral.sh/uv/)（自带 Python 管理）。装包前先 `uv sync --all-extras`。

```bash
# 安装依赖（自动建 .venv）
uv sync --all-extras

# 复制环境变量模板
cp .env.example .env

# CLI 入口
uv run writer --help
uv run writer doctor           # 检查配置
uv run writer new 我的小说       # 创建小说项目目录
uv run writer outline 一句话创意  # 生成最小大纲占位输出

# 测试
uv run pytest                              # 全量
uv run pytest tests/test_engine.py         # 单文件
uv run pytest -k router                    # 按名字匹配
uv run pytest tests/test_engine.py::test_router_classifies_write_command  # 单测
uv run pytest -x --tb=short                # 失败即停 + 紧凑回溯
uv run pytest --cov=writer                 # 覆盖率

# Lint / Type
uv run ruff check src tests
uv run mypy src/writer

# e2e 管道（用 stdin 喂入一次性观察 Done 分支）
printf "/大纲 一个穿越到唐朝的程序员\n" | .venv/bin/writer
```

REPL 模式（默认）：`uv run writer` 后输入 `/帮助` 看命令；退出用 `/退出`。

## 高层架构（四层 + 兼容层）

```
用户输入 → CLI (typer + rich + prompt_toolkit)
              ↓
       L1 IntentRouter (Protocol)        ← writer/routing/
              ↓ AgentAction
       L2 Engine 状态机 (AsyncGenerator)  ← writer/engine/
              ↓
       L3 角色 / 工作流 / 工具            ← writer/{roles,workflows,tools}/
              ↓
       L4 LLM Provider（未来）            ← OpenAI-compatible
```

**接线流**：`用户输入 → deps.route() → router.route() → AgentAction → engine.loop 分发 → run_command ⇒ roles.StoryConsultant / start_workflow ⇒ workflows.run_workflow / call_tool ⇒ tools.*`

### 各包职责

| 包                 | 职责                                                                                                                            | 关键文件                                                                   |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------- | -------------------------------------------------------------------------- |
| `writer.cli`       | L1：REPL 消费者、Typer 子命令、Rich 渲染、`prompt-toolkit` 历史/补全                                                            | `cli/main.py`                                                              |
| `writer.routing`   | L2 前台意图路由：**`IntentRouter` Protocol** + **`RuleBasedIntentRouter` MVP**；`AgentAction` 是路由的输出而非业务 agent 的属性 | `routing/intent_router.py`                                                 |
| `writer.engine`    | L2 状态机 + AsyncGenerator（events / context / deps / config / loop 五个模块）                                                  | `engine/{loop,deps,events,context,config}.py`                              |
| `writer.roles`     | L3 子代理角色（当前只 `StoryConsultant`，含 `draft_outline()`）                                                                 | `roles/story_consultant.py`                                                |
| `writer.workflows` | L3 长任务 stub（`write_chapter` / `review_chapter`）                                                                            | `workflows/{write,review}_chapter.py`                                      |
| `writer.tools`     | L3 Tool 基础设施（Protocol + Registry + Runtime + langchain_bridge + 5 个 builtin）                                             | `tools/{protocol,registry,runtime,langchain_bridge}.py` + `tools/builtin/` |
| `writer.skills`    | L3 技能占位（`HookDesigner` 等未来落地）                                                                                        | `skills/__init__.py`                                                       |
| `writer.agent`     | **兼容层**——re-export 旧的 `WriterCommandAgent` / `NovelAgent` 别名，最终会移除                                                 | `agent/__init__.py`                                                        |
| `writer.config`    | pydantic-settings，`WRITER_*` 环境变量                                                                                          | `config/settings.py`                                                       |
| `writer.project`   | `writer new` 创建的小说项目目录（`manuscript/` `outline/` `characters/` `world/` `notes/`）                                     | `project/workspace.py`                                                     |

### 关键设计约束

- **`IntentRouter` 是 Protocol，不是具体类**。engine 只依赖 Protocol；`RuleBasedIntentRouter` 是无网络 MVP，`LlmIntentRouter`（LangChain structured output）作为同一协议后面的插槽，未来切换不动 `engine/` 或 `cli/`。
- **`EngineDeps` 是 DI 边界**。engine 不直接 new 协作者，所有外部依赖（`router`、`story_consultant`、未来的 `tool_registry` / `workflow_starter`）都通过 Protocol 注入；`production_deps()` 是默认装配。
- **Engine 输出是事件流**（`TextChunk` / `ActionEvent` / `ToolCall` / `ToolResult` / `Interrupt` / `Done` / `ErrorEvent`），全部 `@dataclass(frozen=True)`。CLI 在 `_run_engine` 里 `match` 渲染。
- **REPL 路由原则**：除框架命令（`/退出` `/帮助` `/状态`）外，斜杠命令与自然语言**一律交给 engine**，避免 CLI 层重复维护命令路由。
- **Tool 安全**：所有 builtin Tool 必须经 `runtime.safe_path()` 防越界；`Tool` 必须用**命名 keyword 参数**（`def run(self, runtime, *, path: str)`），不能用 `**kwargs`，否则 LangChain `args_schema` 无法生成。

### 事件流与 Done 分支

`run_engine` 是个 `AsyncIterator[TextChunk | ActionEvent | ToolCall | ToolResult | Interrupt | Done | ErrorEvent]`，每轮产出一个 `Done` 终结。`Done.reason` 当前覆盖七个分支：

- `answered`——`answer_directly` 或 `/大纲`（含 `chapter_count`）
- `command_pending`——其它斜杠命令
- `tool_pending`——保留(目前未使用,实际工具调用走 `tool_completed`)
- `tool_completed`——`call_tool` 真调 `ToolRegistry.invoke()` 后(含 `ToolCall`/`ToolResult` 事件)
- `workflow_pending`——`/写` `/审核` 工作流
- `ask_user`——保留分支(配 `Interrupt` 事件供 REPL driver 拼多轮)
- `aborted`——`ErrorEvent` 后兜底分支(引擎异常/工具异常)

## 测试

- 框架：pytest + pytest-asyncio（`asyncio_mode = "auto"`）
- 当前基线：40 个测试（10 cli + 16 engine + 14 tool），`IntentRouter` Protocol 拆分后新增 `test_rule_based_router_satisfies_protocol`
- 关键覆盖点：router 分类、engine 五种 Done 分支、Tool 路径越界拒绝
- `tests/conftest.py`（如有）会注入 `EngineDeps` 替身

## 设计文档

| 文件                           | 用途                                                                 |
| ------------------------------ | -------------------------------------------------------------------- |
| `docs/技术架构总览.md`         | 四层架构 + LangGraph 状态图 + LangChain 角色定位 + LLM Provider 路由 |
| `docs/命令与用户流程.md`       | 24 个 REPL 命令 + S0-S5 项目状态机 + 命令 × 状态可用性矩阵           |
| `docs/技术架构细节.md`         | 工程实现细节                                                         |
| `docs/设计文档.md`             | 早期总体设计                                                         |
| `技术难点与解决方案备忘/01-17` | 17 个技术决策备忘（状态机、RAG、Tool 设计、Agent 架构模式等）        |

修改任何模块前，先看对应 `备忘/*.md`——里面记录了选型理由与"不做什么"清单。
